"""Phase 5 — free-tools funnel tests (CCTV calculator)."""
from app.services.cctv_calculator import CCTVCalcInput, estimate_cctv
from app.api.v1.endpoints import tools as tools_router


def test_estimate_basic_home():
    est = estimate_cctv(CCTVCalcInput(site_type="home", area_sqm=120, entry_points=2, floors=1))
    assert est.recommended_cameras >= 1
    assert est.indoor_cameras >= est.outdoor_cameras
    m = est.material_estimate
    assert m["total"] == m["cameras"] + m["nvr"] + m["storage"]
    assert est.currency == "USD"


def test_site_type_sets_minimum_cameras():
    home = estimate_cctv(CCTVCalcInput(site_type="home", area_sqm=5, entry_points=0, floors=1))
    warehouse = estimate_cctv(CCTVCalcInput(site_type="warehouse", area_sqm=5, entry_points=0, floors=1))
    assert warehouse.recommended_cameras >= 4  # warehouse floor
    assert home.recommended_cameras == 1       # home floor


def test_budget_tier_changes_unit_cost():
    low = estimate_cctv(CCTVCalcInput(site_type="home", area_sqm=200, entry_points=3, budget_tier="low"))
    high = estimate_cctv(CCTVCalcInput(site_type="home", area_sqm=200, entry_points=3, budget_tier="high"))
    assert high.material_estimate["cameras"] > low.material_estimate["cameras"]
    assert high.material_estimate["total"] > low.material_estimate["total"]


def test_outdoor_perimeter_adds_cameras():
    none = estimate_cctv(CCTVCalcInput(site_type="home", area_sqm=100, perimeter_m=0))
    some = estimate_cctv(CCTVCalcInput(site_type="home", area_sqm=100, perimeter_m=150))
    assert some.outdoor_cameras >= 1
    assert some.recommended_cameras > none.recommended_cameras


async def test_cctv_calculator_endpoint_returns_cta():
    res = await tools_router.cctv_calculator(CCTVCalcInput(site_type="business", area_sqm=300, entry_points=4))
    assert res["cta"] == "/cctv/intake"
    assert res["recommended_cameras"] >= 1
