"""Phase 5 — Supplier side API (begin).

Public catalogue search + per-job material recommendations. The recommend
endpoint is customer-only (job owner) and ties a job's brief to the materials it
needs and the suppliers who stock them.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.dependencies import get_db, get_current_user
from app.models.all_models import Job, Product, Supplier, MaterialOrder
from app.services.supplier_service import (
    recommend_materials_for_job,
    search_products,
    match_products_for_bom,
    place_material_order,
    fulfill_order,
)

router = APIRouter()


@router.get("/products", response_model=dict)
async def list_products(
    category: Optional[str] = None,
    country: Optional[str] = None,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
) -> dict:
    products = await search_products(db, category=category, country=country, limit=limit)
    out = []
    for p in products:
        sup = await db.get(Supplier, p.supplier_id)
        out.append({
            "id": p.id, "name": p.name, "category": p.category, "price": p.price,
            "currency": p.currency, "stock_qty": p.stock_qty,
            "supplier": sup.name if sup else None, "supplier_verified": bool(sup and sup.is_verified),
        })
    return {"products": out, "count": len(out)}


@router.post("/recommend", response_model=dict)
async def recommend_for_job(
    payload: dict,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    job_id = payload.get("job_id")
    job = await db.get(Job, job_id) if job_id is not None else None
    if not job or job.customer_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    bom = recommend_materials_for_job(job)
    products = await search_products(db)
    matches = match_products_for_bom(products, bom)

    materials = []
    for item in bom:
        m = matches.get(item["name"])
        supplier_name = None
        if m:
            sup = await db.get(Supplier, m.supplier_id)
            supplier_name = sup.name if sup else None
        materials.append({
            "name": item["name"],
            "quantity": item["quantity"],
            "estimated_unit_price": item["estimated_unit_price"],
            "matched_product": (
                {"id": m.id, "name": m.name, "price": m.price, "supplier": supplier_name}
                if m else None
            ),
        })
    return {"job_id": job.id, "category": job.category, "materials": materials}


@router.post("/jobs/{job_id}/order", response_model=dict)
async def order_materials(
    job_id: int,
    payload: dict = {},
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if current_user.role not in ("customer", "contractor", "admin"):
        raise HTTPException(status_code=403, detail="Not authorized")
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.role == "customer" and job.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your job")

    supplier_id = payload.get("supplier_id")
    order = await place_material_order(db, job, supplier_id=supplier_id)
    await db.commit()
    await db.refresh(order)
    return {
        "order_id": order.id,
        "job_id": job.id,
        "status": order.status,
        "total": order.total,
        "currency": order.currency,
    }


@router.post("/orders/{order_id}/fulfill", response_model=dict)
async def fulfill_material_order(
    order_id: int,
    current_user=Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if current_user.role not in ("contractor", "admin"):
        raise HTTPException(status_code=403, detail="Only contractors/admins can fulfil orders")
    order = await fulfill_order(db, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")
    await db.commit()
    await db.refresh(order)
    return {
        "order_id": order.id,
        "status": order.status,
        "job_id": order.job_id,
    }
