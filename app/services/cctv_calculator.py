"""Phase 5 — Free-tools funnel: CCTV calculator.

A public, ad-supported estimator that turns a few site parameters into a
recommended camera plan + rough material budget, then funnels the user into the
ServiceSync CCTV marketplace (``/cctv/intake``). Pure, deterministic maths — no
LLM, no network — so it is fast, cheap, and always available (SEO + funnel).

Add more vertical calculators later (solar, quotation generator, …) by following
the same shape.
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class CCTVCalcInput(BaseModel):
    site_type: str = Field(default="home", description="home|business|warehouse|retail")
    floors: int = Field(default=1, ge=1, le=50)
    area_sqm: float = Field(default=100.0, ge=5, le=100000)
    perimeter_m: float = Field(default=0.0, ge=0, le=5000)  # outdoor coverage
    entry_points: int = Field(default=2, ge=0, le=200)
    wants_remote_viewing: bool = True
    wants_night_vision: bool = True
    wants_audio: bool = False
    recording_days: int = Field(default=14, ge=1, le=365)
    budget_tier: str = Field(default="mid", description="low|mid|high")


class CCTVEstimate(BaseModel):
    site_type: str
    recommended_cameras: int
    indoor_cameras: int
    outdoor_cameras: int
    suggested_features: list[str]
    recording_days: int
    storage_tb_approx: float
    material_estimate: dict  # {cameras, nvr, storage, total} in `currency`
    currency: str = "USD"
    notes: str


# Per-tier unit economics used for the rough material budget.
_TIERS = {
    "low":  {"cam": 45, "nvr": 110, "storage_per_tb": 55},
    "mid":  {"cam": 95, "nvr": 190, "storage_per_tb": 110},
    "high": {"cam": 190, "nvr": 360, "storage_per_tb": 210},
}


def estimate_cctv(inp: CCTVCalcInput) -> CCTVEstimate:
    site = inp.site_type.lower()
    tier = _TIERS.get(inp.budget_tier.lower(), _TIERS["mid"])

    # Camera count heuristic: coverage of interior area + entry points + outdoor
    # perimeter, with a sensible floor by site type.
    area_cams = max(1, round(inp.area_sqm / 45))
    entry_cams = inp.entry_points
    floor_cams = max(0, inp.floors - 1)  # landings/stairs between floors
    outdoor_cams = round(inp.perimeter_m / 15) if inp.perimeter_m else 0
    base_by_site = {"warehouse": 4, "retail": 2, "business": 2, "home": 1}.get(site, 1)

    indoor = area_cams + entry_cams + floor_cams
    outdoor = outdoor_cams
    total = indoor + outdoor
    total = max(total, base_by_site)  # never recommend fewer than the site floor

    features = ["motion_alerts", "local_recording"]
    if inp.wants_remote_viewing:
        features.append("remote_viewing")
    if inp.wants_night_vision:
        features.append("night_vision")
    if inp.wants_audio:
        features.append("two_way_audio")

    # Storage: ~ (cameras * recording_days * 0.02 TB) crude rule of thumb.
    storage_tb = round(total * inp.recording_days * 0.02, 2)
    storage_tb = max(storage_tb, 0.5)

    cameras_cost = total * tier["cam"]
    nvr_cost = tier["nvr"]
    storage_cost = round(storage_tb * tier["storage_per_tb"])
    total_cost = cameras_cost + nvr_cost + storage_cost

    notes = (
        "Estimate only — final scope/price depends on site survey and installer quote. "
        "Use the button below to describe your site and get matched with installers."
    )

    return CCTVEstimate(
        site_type=site,
        recommended_cameras=total,
        indoor_cameras=indoor,
        outdoor_cameras=outdoor,
        suggested_features=features,
        recording_days=inp.recording_days,
        storage_tb_approx=storage_tb,
        material_estimate={
            "cameras": cameras_cost,
            "nvr": nvr_cost,
            "storage": storage_cost,
            "total": total_cost,
        },
        currency="USD",
        notes=notes,
    )
