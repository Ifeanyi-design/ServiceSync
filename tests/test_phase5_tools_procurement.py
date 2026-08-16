"""Phase 5 — quotation calculator + procurement/delivery workflow tests."""
from app.services.quote_calculator import QuoteCalcInput, estimate_quote
from app.api.v1.endpoints import tools as tools_router
from app.core.database import async_session_maker
from app.models.all_models import User, Job, Supplier, Product, MaterialOrder
from sqlmodel import select
from app.api.v1.endpoints import suppliers as suppliers_router


# ── Quotation calculator ─────────────────────────────────────────────────────
def test_quote_estimate_includes_materials_and_tax():
    est = estimate_quote(QuoteCalcInput(trade="plumbing", job_size="medium",
                                       complexity="standard", include_materials=True))
    assert est.subtotal > 0
    assert est.tax == round(est.subtotal * 0.075, 2)
    assert est.total == round(est.subtotal + est.tax, 2)
    assert any("Materials" in li["description"] for li in est.line_items)


def test_quote_complexity_scales_labour():
    simple = estimate_quote(QuoteCalcInput(trade="plumbing", job_size="medium", complexity="simple"))
    complex_ = estimate_quote(QuoteCalcInput(trade="plumbing", job_size="medium", complexity="complex"))
    simple_labour = next(li["amount"] for li in simple.line_items if "labour" in li["description"])
    complex_labour = next(li["amount"] for li in complex_.line_items if "labour" in li["description"])
    assert complex_labour > simple_labour


async def test_quote_endpoint_cta():
    out = await tools_router.quote_calculator(QuoteCalcInput(trade="electrician"))
    assert out["cta"] == "/contractors?profession=electrician"
    assert out["total"] > 0


# ── Procurement / delivery ─────────────────────────────────────────────────────
async def test_order_and_fulfil_materials():
    async with async_session_maker() as db:
        customer = User(email="ord@x.com", hashed_password="z", role="customer", full_name="OC")
        contractor = User(email="ordc@x.com", hashed_password="z", role="contractor", full_name="Contr")
        supplier = Supplier(name="CamWorld", country="NG", city="Lagos", is_verified=True)
        db.add_all([customer, contractor, supplier])
        await db.flush()
        product = Product(supplier_id=supplier.id, name="4MP Camera", category="cctv_camera", price=90.0)
        db.add(product)
        job = Job(customer_id=customer.id, description="cctv", category="cctv", status="open",
                 brief={"category": "cctv", "cctv": {"camera_count": 4}})
        db.add(job)
        await db.flush()

        # Customer places a material order for the job.
        order = await suppliers_router.order_materials(job.id, {"supplier_id": supplier.id}, customer, db)
        assert order["status"] == "ordered"
        assert order["total"] > 0

        # Contractor fulfils it.
        fulfilled = await suppliers_router.fulfill_material_order(order["order_id"], contractor, db)
        assert fulfilled["status"] == "delivered"

        # Both writes must be committed (regression guard for missing commit).
        await db.commit()
        persisted = (await db.exec(select(MaterialOrder).where(MaterialOrder.job_id == job.id))).first()
        assert persisted is not None
        assert persisted.status == "delivered"
