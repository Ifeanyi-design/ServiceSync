"""Phase 5 — additional funnel estimators (BOM + market price range)."""
from app.services.bom_calculator import BOMCalcInput, estimate_bom
from app.services.price_estimator import PriceEstimatorInput, estimate_service_price, region_factor
from app.api.v1.endpoints import tools as tools_router


def test_bom_estimate_includes_fixed_and_scaled_lines():
    est = estimate_bom(BOMCalcInput(trade="cctv", job_size="medium"))
    # medium unit trade -> 3 cameras by default; NVR is a fixed one-off line.
    camera = next(m for m in est.materials if m.name == "Camera")
    nvr = next(m for m in est.materials if m.name == "NVR / recorder")
    assert camera.quantity == 3
    assert nvr.quantity == 1
    assert est.labour > 0
    assert est.total > est.subtotal
    assert est.currency == "USD"


def test_bom_scope_override_and_quality():
    base = estimate_bom(BOMCalcInput(trade="painting", job_size="medium", scope=20.0))
    premium = estimate_bom(BOMCalcInput(trade="painting", job_size="medium", scope=20.0, quality="premium"))
    assert base.scope == 20.0
    assert premium.total > base.total


def test_price_estimator_range_ordering():
    est = estimate_service_price(PriceEstimatorInput(trade="plumbing", job_size="medium", region="us"))
    assert est.low < est.median < est.high
    # US should be pricier than Nigeria for the same job.
    ng = estimate_service_price(PriceEstimatorInput(trade="plumbing", job_size="medium", region="ng"))
    assert est.median > ng.median


def test_region_factor_default_and_known():
    assert region_factor("zz") == 1.0
    assert region_factor("us") > region_factor("ng")


async def test_bom_and_price_endpoints_return_cta():
    bom = await tools_router.bom_calculator(BOMCalcInput(trade="solar"))
    assert bom["cta"] == "/contractors?profession=solar"
    assert bom["total"] > 0
    price = await tools_router.price_estimator(PriceEstimatorInput(trade="hvac", job_size="large", region="uk"))
    assert price["cta"] == "/contractors?profession=hvac"
    assert price["high"] > price["low"]
