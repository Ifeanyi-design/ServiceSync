"""Phase 5 — Free-tools funnel: solar estimator.

Public, ad-supported solar system estimator. Deterministic (no LLM/network):
turns electricity usage + roof/sun inputs into a recommended system size, panel
count, battery, and a rough material budget. Funnels into the marketplace
(``/contractors?profession=solar``). Same shape as the CCTV calculator so more
tools drop in easily.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class SolarCalcInput(BaseModel):
    monthly_kwh: float = Field(default=400.0, ge=0, le=100000)  # current usage
    roof_area_sqm: float = Field(default=30.0, ge=1, le=100000)
    sun_hours: float = Field(default=4.5, ge=0.5, le=12)       # peak sun hrs/day
    battery_backup: bool = True
    budget_tier: str = Field(default="mid", description="low|mid|high")


class SolarEstimate(BaseModel):
    system_size_kw: float
    panel_watt: int
    panel_count: int
    battery_kwh: float
    suggested_features: list[str]
    material_estimate: dict  # {panels, inverter, battery, installation, total}
    currency: str = "USD"
    notes: str


_TIERS = {
    "low":  {"panel": 90, "inverter": 600, "battery_per_kwh": 200, "install": 800, "watt": 400},
    "mid":  {"panel": 160, "inverter": 1100, "battery_per_kwh": 350, "install": 1500, "watt": 450},
    "high": {"panel": 260, "inverter": 2000, "battery_per_kwh": 550, "install": 3000, "watt": 550},
}


def estimate_solar(inp: SolarCalcInput) -> SolarEstimate:
    tier = _TIERS.get(inp.budget_tier.lower(), _TIERS["mid"])

    # System size: monthly kWh / (days * peak-sun * efficiency), in kW.
    system_kw = inp.monthly_kwh / (30.0 * inp.sun_hours * 0.8)
    system_kw = max(system_kw, 0.5)

    panel_watt = tier["watt"]
    panel_count = max(1, -(-int(system_kw * 1000) // panel_watt))  # ceil division

    battery_kwh = 0.0
    if inp.battery_backup:
        battery_kwh = max(5.0, round(system_kw * 3.0))

    features = ["monitoring_app", "inverter"]
    if inp.battery_backup:
        features.append("battery_backup")

    panels_cost = panel_count * tier["panel"]
    inverter_cost = tier["inverter"]
    battery_cost = round(battery_kwh * tier["battery_per_kwh"])
    install_cost = tier["install"]
    total = panels_cost + inverter_cost + battery_cost + install_cost

    notes = (
        "Estimate only — final design/price depends on a site survey and installer "
        "quote. Use the button below to find a verified solar installer."
    )

    return SolarEstimate(
        system_size_kw=round(system_kw, 2),
        panel_watt=panel_watt,
        panel_count=panel_count,
        battery_kwh=battery_kwh,
        suggested_features=features,
        material_estimate={
            "panels": panels_cost,
            "inverter": inverter_cost,
            "battery": battery_cost,
            "installation": install_cost,
            "total": total,
        },
        currency="USD",
        notes=notes,
    )
