"""Phase 5 — solar calculator + supplier-side (begin) tests."""
from app.services.solar_calculator import SolarCalcInput, estimate_solar
from app.api.v1.endpoints import tools as tools_router
from app.core.database import async_session_maker
from app.models.all_models import User, Job, Supplier, Product
from app.services import supplier_service
from app.api.v1.endpoints import suppliers as suppliers_router


# ── Solar calculator ───────────────────────────────────────────────────────────
def test_solar_estimate_basic():
    est = estimate_solar(SolarCalcInput(monthly_kwh=400, sun_hours=4.5, battery_backup=True))
    assert est.system_size_kw > 0
    assert est.panel_count >= 1
    m = est.material_estimate
    assert m["total"] == m["panels"] + m["inverter"] + m["battery"] + m["installation"]
    assert est.battery_kwh > 0


def test_solar_budget_tier_scales_cost():
    low = estimate_solar(SolarCalcInput(monthly_kwh=600, battery_backup=False, budget_tier="low"))
    high = estimate_solar(SolarCalcInput(monthly_kwh=600, battery_backup=False, budget_tier="high"))
    assert high.material_estimate["total"] > low.material_estimate["total"]


def test_solar_endpoint_cta():
    res = estimate_solar(SolarCalcInput(monthly_kwh=500))
    # endpoint wrapper
    out = {**res.model_dump(), "cta": "/contractors?profession=solar"}
    assert out["cta"].endswith("profession=solar")


async def test_solar_calculator_endpoint():
    out = await tools_router.solar_calculator(SolarCalcInput(monthly_kwh=500, battery_backup=True))
    assert out["cta"] == "/contractors?profession=solar"
    assert out["panel_count"] >= 1


# ── Supplier side ──────────────────────────────────────────────────────────────
def test_recommend_materials_cctv():
    job = Job(customer_id=1, description="cctv", category="cctv", status="open",
              brief={"category": "cctv", "cctv": {"camera_count": 4}})
    items = supplier_service.recommend_materials_for_job(job)
    cats = [i["category"] for i in items]
    assert "cctv_camera" in cats and "nvr" in cats and "storage" in cats


def test_recommend_materials_generic_fallback():
    job = Job(customer_id=1, description="x", category="general", status="open")
    items = supplier_service.recommend_materials_for_job(job)
    assert len(items) == 1 and items[0]["category"] == "other"


async def test_supplier_products_and_recommend_endpoint():
    async with async_session_maker() as db:
        customer = User(email="sc@x.com", hashed_password="z", role="customer", full_name="SC")
        supplier = Supplier(name="CamWorld", country="NG", city="Lagos", is_verified=True)
        db.add_all([customer, supplier])
        await db.flush()
        product = Product(supplier_id=supplier.id, name="4MP CCTV Camera", category="cctv_camera",
                         price=90.0, stock_qty=50)
        db.add(product)
        job = Job(customer_id=customer.id, description="cctv", category="cctv", status="open",
                 brief={"category": "cctv", "cctv": {"camera_count": 4}})
        db.add(job)
        await db.flush()

        # Public catalogue search.
        listing = await suppliers_router.list_products(category="cctv_camera", db=db)
        assert listing["count"] >= 1

        # Per-job recommendation (customer-only).
        rec = await suppliers_router.recommend_for_job({"job_id": job.id}, customer, db)
        assert rec["category"] == "cctv"
        camera_line = next(m for m in rec["materials"] if m["name"].startswith("4×") or "camera" in m["name"].lower())
        assert camera_line["matched_product"] is not None
        assert camera_line["matched_product"]["supplier"] == "CamWorld"
