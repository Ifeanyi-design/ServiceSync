"""Phase 5 — Free-tools funnel: quotation generator.

Public, ad-supported service-price estimator. Turns a trade + job size +
complexity into a structured labour/materials quote (line items, callout fee,
tax, total) and funnels the user to a verified pro. Deterministic — no LLM/network.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class QuoteCalcInput(BaseModel):
    trade: str = Field(default="plumbing", description="plumber|electrician|cctv|solar|hvac|cleaning|handyman")
    job_size: str = Field(default="medium", description="small|medium|large")
    complexity: str = Field(default="standard", description="simple|standard|complex")
    region_factor: float = Field(default=1.0, ge=0.5, le=3.0)  # city cost multiplier
    include_materials: bool = True
    tax_rate: float = Field(default=0.075, ge=0, le=0.5)


class QuoteEstimate(BaseModel):
    trade: str
    job_size: str
    line_items: list[dict]
    subtotal: float
    callout_fee: float
    tax: float
    total: float
    currency: str = "USD"
    notes: str


# Base labour cost by trade + size (pre complexity/region).
_LABOUR = {
    "plumbing":   {"small": 120, "medium": 280, "large": 520},
    "electrician": {"small": 130, "medium": 300, "large": 560},
    "cctv":       {"small": 180, "medium": 380, "large": 700},
    "solar":      {"small": 600, "medium": 1400, "large": 2800},
    "hvac":       {"small": 200, "medium": 460, "large": 900},
    "cleaning":   {"small": 90,  "medium": 200, "large": 420},
    "handyman":   {"small": 80,  "medium": 170, "large": 340},
}
_COMPLEXITY = {"simple": 0.8, "standard": 1.0, "complex": 1.4}
_CALL_FEE = 35.0
# Trades that typically include a materials line.
_MATERIAL_TRADES = {"plumbing", "electrician", "cctv", "solar", "hvac"}


def estimate_quote(inp: QuoteCalcInput) -> QuoteEstimate:
    trade = inp.trade.lower()
    size = inp.job_size.lower()
    cx = _COMPLEXITY.get(inp.complexity.lower(), 1.0)

    labour = _LABOUR.get(trade, _LABOUR["handyman"]).get(size, 200)
    labour = round(labour * cx * inp.region_factor)

    items = [{"description": f"{trade.title()} labour ({size}, {inp.complexity})", "amount": labour}]

    materials = 0
    if inp.include_materials and trade in _MATERIAL_TRADES:
        materials = round(labour * 0.5)
        items.append({"description": "Materials & parts", "amount": materials})

    subtotal = labour + materials + _CALL_FEE
    tax = round(subtotal * inp.tax_rate, 2)
    total = round(subtotal + tax, 2)

    notes = (
        "Estimate only — final price depends on an on-site assessment. Use the "
        "button below to get matched with a verified professional."
    )
    return QuoteEstimate(
        trade=trade, job_size=size, line_items=items,
        subtotal=round(subtotal, 2), callout_fee=_CALL_FEE, tax=tax, total=total,
        currency="USD", notes=notes,
    )
