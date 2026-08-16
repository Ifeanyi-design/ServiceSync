"""Phase 5 — Supplier side (begin).

Connects a completed job brief to the materials it needs and the suppliers who
sell them. Deterministic recommendation (no LLM), plus a catalogue search.
Procurement/delivery workflow is layered on later.
"""
from __future__ import annotations

from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.all_models import Job, Product, Supplier, JobMaterial, MaterialOrder

# Mid-tier reference prices used to seed a recommended bill of materials when no
# catalogue match is available yet.
_REF_PRICES = {
    "cctv_camera": 95.0,
    "nvr": 190.0,
    "storage": 110.0,
    "solar_panel": 160.0,
    "inverter": 1100.0,
    "battery": 350.0,
}


def recommend_materials_for_job(job: Job) -> list[dict]:
    """Derive a suggested bill of materials from a job's structured brief.

    Returns a list of dicts: {name, category, quantity, estimated_unit_price}.
    """
    items: list[dict] = []
    cat = (job.category or "general").lower()
    brief = job.brief or {}

    if cat == "cctv" and brief.get("cctv"):
        c = brief["cctv"]
        qty = c.get("camera_count") or 2
        items.append({"name": f"{qty}× CCTV camera", "category": "cctv_camera",
                      "quantity": qty, "estimated_unit_price": _REF_PRICES["cctv_camera"]})
        items.append({"name": "NVR / recorder", "category": "nvr",
                      "quantity": 1, "estimated_unit_price": _REF_PRICES["nvr"]})
        items.append({"name": "Storage / HDD", "category": "storage",
                      "quantity": 1, "estimated_unit_price": _REF_PRICES["storage"]})
    elif cat == "solar" and brief.get("solar"):
        s = brief["solar"]
        panels = s.get("panel_count") or 4
        items.append({"name": f"{panels}× solar panel", "category": "solar_panel",
                      "quantity": panels, "estimated_unit_price": _REF_PRICES["solar_panel"]})
        items.append({"name": "Inverter", "category": "inverter",
                      "quantity": 1, "estimated_unit_price": _REF_PRICES["inverter"]})
        if s.get("battery_kwh"):
            items.append({"name": f"{s['battery_kwh']} kWh battery", "category": "battery",
                          "quantity": 1, "estimated_unit_price": _REF_PRICES["battery"]})
    else:
        # Generic fallback: a single catch-all line so the BOM is never empty.
        items.append({"name": "Job materials", "category": "other",
                      "quantity": 1, "estimated_unit_price": 0.0})
    return items


async def search_products(
    db: AsyncSession,
    category: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = 50,
) -> list[Product]:
    q = select(Product).join(Supplier)
    if category:
        q = q.where(Product.category == category.lower())
    if country:
        q = q.where(Supplier.country == country)
    q = q.limit(limit)
    res = await db.exec(q)
    return res.all()


def match_products_for_bom(db_products: list[Product], bom: list[dict]) -> dict[str, Optional[Product]]:
    """Best catalogue match per BOM line item, by category."""
    by_cat: dict[str, list[Product]] = {}
    for p in db_products:
        by_cat.setdefault(p.category, []).append(p)
    return {item["name"]: (by_cat.get(item["category"]) or [None])[0] for item in bom}


async def create_bom_for_job(db: AsyncSession, job: Job) -> list[JobMaterial]:
    """Persist the recommended BOM for a job as JobMaterial rows."""
    bom = recommend_materials_for_job(job)
    rows = []
    for item in bom:
        row = JobMaterial(
            job_id=job.id,
            name=item["name"],
            quantity=item["quantity"],
            estimated_unit_price=item["estimated_unit_price"],
            currency="USD",
            source="recommended",
            status="suggested",
        )
        db.add(row)
        rows.append(row)
    await db.flush()
    return rows


async def place_material_order(
    db: AsyncSession, job: Job, supplier_id: Optional[int] = None
) -> MaterialOrder:
    """Place a procurement order for a job's recommended bill of materials.

    Creates the BOM rows (if not present) and a MaterialOrder, marking the items
    as ``ordered``. (Idempotency is not enforced here — a real order placement.)
    """
    rows = await create_bom_for_job(db, job)
    total = sum((r.estimated_unit_price or 0) * r.quantity for r in rows)
    order = MaterialOrder(
        job_id=job.id, supplier_id=supplier_id, status="ordered",
        total=round(total, 2), currency="USD",
    )
    db.add(order)
    await db.flush()
    for r in rows:
        r.order_id = order.id
        r.status = "ordered"
    await db.flush()
    return order


async def fulfill_order(db: AsyncSession, order_id: int) -> MaterialOrder:
    """Mark a material order (and its line items) as delivered."""
    order = await db.get(MaterialOrder, order_id)
    if not order:
        return None
    order.status = "delivered"
    res = await db.exec(select(JobMaterial).where(JobMaterial.order_id == order_id))
    for r in res.all():
        r.status = "delivered"
    await db.flush()
    return order
