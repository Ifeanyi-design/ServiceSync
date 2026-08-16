"""Phase 5 — Free-tools funnel: project / bill-of-materials calculator.

Public, ad-supported estimator that turns a trade + scope into a structured
materials bill of materials and a labour estimate. Deterministic — no LLM/network.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# Per-trade bill-of-materials templates. `basis` is "area" (per m2) or "unit"
# (per camera / kW / fixture / task). A material line with fixed=True is a single
# one-off item (e.g. an NVR) regardless of scope.
_BOM_TEMPLATES: dict = {
    "painting": {"basis": "area", "labour_per": 14, "materials": [
        {"name": "Primer", "per": 0.12, "unit": "L", "price": 9},
        {"name": "Paint (2 coats)", "per": 0.22, "unit": "L", "price": 20},
        {"name": "Consumables", "per": 1.0, "unit": "m2", "price": 3},
    ]},
    "flooring": {"basis": "area", "labour_per": 16, "materials": [
        {"name": "Floor finish", "per": 1.05, "unit": "m2", "price": 24},
        {"name": "Underlay", "per": 1.05, "unit": "m2", "price": 6},
    ]},
    "tiling": {"basis": "area", "labour_per": 22, "materials": [
        {"name": "Tiles", "per": 1.1, "unit": "m2", "price": 18},
        {"name": "Adhesive & grout", "per": 1.0, "unit": "m2", "price": 6},
    ]},
    "roofing": {"basis": "area", "labour_per": 20, "materials": [
        {"name": "Roof sheets", "per": 1.1, "unit": "m2", "price": 16},
        {"name": "Underfelt", "per": 1.1, "unit": "m2", "price": 4},
    ]},
    "cctv": {"basis": "unit", "unit_label": "camera", "labour_per": 70, "materials": [
        {"name": "Camera", "per": 1.0, "unit": "unit", "price": 95},
        {"name": "NVR / recorder", "per": 0.0, "unit": "unit", "price": 190, "fixed": True},
        {"name": "Cabling", "per": 20.0, "unit": "m", "price": 1.5},
    ]},
    "solar": {"basis": "unit", "unit_label": "kW", "labour_per": 220, "materials": [
        {"name": "Panel", "per": 1.0, "unit": "unit", "price": 160},
        {"name": "Inverter", "per": 0.0, "unit": "unit", "price": 1100, "fixed": True},
        {"name": "Battery", "per": 0.0, "unit": "unit", "price": 350, "fixed": True},
    ]},
    "plumbing": {"basis": "unit", "unit_label": "fixture", "labour_per": 90, "materials": [
        {"name": "Pipes & fittings", "per": 1.0, "unit": "set", "price": 40},
        {"name": "Fixtures", "per": 1.0, "unit": "unit", "price": 60},
    ]},
    "electrical": {"basis": "unit", "unit_label": "point", "labour_per": 85, "materials": [
        {"name": "Cable & conduit", "per": 1.0, "unit": "set", "price": 35},
        {"name": "Outlets / switches", "per": 1.0, "unit": "unit", "price": 12},
    ]},
    "hvac": {"basis": "unit", "unit_label": "unit", "labour_per": 180, "materials": [
        {"name": "AC unit", "per": 1.0, "unit": "unit", "price": 450},
        {"name": "Mounting kit", "per": 1.0, "unit": "set", "price": 40},
    ]},
    "cleaning": {"basis": "area", "labour_per": 10, "materials": [
        {"name": "Cleaning supplies", "per": 1.0, "unit": "m2", "price": 2},
    ]},
    "handyman": {"basis": "unit", "unit_label": "task", "labour_per": 65, "materials": [
        {"name": "Materials", "per": 1.0, "unit": "set", "price": 30},
    ]},
}

_QUALITY = {"economy": 0.85, "standard": 1.0, "premium": 1.3}
_DEFAULT_SCOPE_AREA = {"small": 10, "medium": 30, "large": 80}
_DEFAULT_SCOPE_UNIT = {"small": 1, "medium": 3, "large": 8}


class BOMCalcInput(BaseModel):
    trade: str = Field(default="painting", description="trade key")
    job_size: str = Field(default="medium", description="small|medium|large")
    scope: float | None = Field(default=None, description="area in m2 (area trades) or count (unit trades); auto by size if omitted")
    quality: str = Field(default="standard", description="economy|standard|premium")
    region_factor: float = Field(default=1.0, ge=0.5, le=3.0)
    tax_rate: float = Field(default=0.075, ge=0, le=0.5)


class BOMLine(BaseModel):
    name: str
    quantity: float
    unit: str
    unit_price: float
    amount: float


class BOMEstimate(BaseModel):
    trade: str
    basis: str
    scope: float
    quality: str
    materials: list[BOMLine]
    labour: float
    subtotal: float
    tax: float
    total: float
    currency: str = "USD"
    notes: str


def estimate_bom(inp: BOMCalcInput) -> BOMEstimate:
    trade = inp.trade.lower()
    tpl = _BOM_TEMPLATES.get(trade, _BOM_TEMPLATES["handyman"])
    basis = tpl["basis"]
    size = inp.job_size.lower()

    if inp.scope is not None:
        scope = float(inp.scope)
    else:
        scope = float((_DEFAULT_SCOPE_AREA if basis == "area" else _DEFAULT_SCOPE_UNIT).get(size, 10))

    quality = _QUALITY.get(inp.quality.lower(), 1.0)

    materials: list[BOMLine] = []
    materials_total = 0.0
    for m in tpl["materials"]:
        if m.get("fixed"):
            qty = 1.0
        else:
            qty = round(m["per"] * scope, 2)
        amount = round(qty * m["price"], 2)
        materials_total += amount
        materials.append(BOMLine(name=m["name"], quantity=qty, unit=m["unit"],
                                 unit_price=m["price"], amount=amount))

    labour = round(tpl["labour_per"] * scope * quality * inp.region_factor, 2)
    subtotal = round(materials_total + labour, 2)
    tax = round(subtotal * inp.tax_rate, 2)
    total = round(subtotal + tax, 2)

    notes = (
        "Estimate only — prices vary by brand and site conditions. Use the button "
        "below to get matched with a verified professional who can price it precisely."
    )
    return BOMEstimate(
        trade=trade, basis=basis, scope=scope, quality=inp.quality.lower(),
        materials=materials, labour=labour, subtotal=subtotal, tax=tax,
        total=total, currency="USD", notes=notes,
    )
