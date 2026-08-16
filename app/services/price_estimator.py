"""Phase 5 — Free-tools funnel: market service-price estimator.

Public, ad-supported estimator that returns a realistic low/median/high price
range for a trade in a region. Deterministic — no LLM/network.
"""
from __future__ import annotations

from pydantic import BaseModel, Field

# Region cost multipliers relative to a global baseline (USD).
_REGION_FACTORS: dict = {
    "ng": 0.6, "gh": 0.65, "ke": 0.7, "za": 0.8, "ae": 1.1,
    "eu": 1.25, "uk": 1.3, "us": 1.4, "ca": 1.35, "au": 1.35,
}

# (low, high) baseline ranges per trade + job size, pre region/complexity.
_BASE_RANGES: dict = {
    "plumbing":   {"small": (80, 180), "medium": (200, 450), "large": (500, 1100)},
    "electrician": {"small": (90, 200), "medium": (220, 480), "large": (550, 1200)},
    "cctv":       {"small": (250, 600), "medium": (600, 1400), "large": (1400, 3200)},
    "solar":      {"small": (900, 2200), "medium": (2500, 6000), "large": (6000, 14000)},
    "hvac":       {"small": (180, 450), "medium": (500, 1200), "large": (1200, 3000)},
    "painting":   {"small": (120, 300), "medium": (350, 800), "large": (900, 2200)},
    "flooring":   {"small": (150, 400), "medium": (450, 1100), "large": (1200, 3000)},
    "tiling":     {"small": (140, 360), "medium": (400, 1000), "large": (1100, 2800)},
    "roofing":    {"small": (300, 700), "medium": (900, 2200), "large": (2500, 6000)},
    "cleaning":   {"small": (60, 150), "medium": (160, 380), "large": (400, 950)},
    "handyman":   {"small": (70, 160), "medium": (180, 420), "large": (450, 1000)},
}
_COMPLEXITY = {"simple": 0.85, "standard": 1.0, "complex": 1.35}


class PriceEstimatorInput(BaseModel):
    trade: str = Field(default="plumbing", description="trade key")
    job_size: str = Field(default="medium", description="small|medium|large")
    region: str = Field(default="default", description="ng|gh|ke|za|us|uk|eu|ae|ca|au|default")
    complexity: str = Field(default="standard", description="simple|standard|complex")


class PriceEstimate(BaseModel):
    trade: str
    job_size: str
    region: str
    low: float
    median: float
    high: float
    currency: str = "USD"
    notes: str


def region_factor(region: str) -> float:
    return float(_REGION_FACTORS.get(region.lower(), 1.0))


def estimate_service_price(inp: PriceEstimatorInput) -> PriceEstimate:
    trade = inp.trade.lower()
    size = inp.job_size.lower()
    cx = _COMPLEXITY.get(inp.complexity.lower(), 1.0)
    rf = region_factor(inp.region)

    low, high = _BASE_RANGES.get(trade, _BASE_RANGES["handyman"]).get(size, (150, 400))
    low = round(low * rf * cx)
    high = round(high * rf * cx)
    median = round((low + high) / 2)

    notes = (
        "Indicative market range — actual quotes vary by site and provider. "
        "Get matched with a verified professional below for a firm price."
    )
    return PriceEstimate(
        trade=trade, job_size=size, region=inp.region.lower(),
        low=low, median=median, high=high, currency="USD", notes=notes,
    )
