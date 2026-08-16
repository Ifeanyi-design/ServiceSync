"""Phase 0 — escrow regression tests (payment edge cases).

Locks in the double-receipt / TOCTOU guard added to escrow_service.py
(see docs/ROADMAP.md §3.1 and §4 Phase 0). Uses a real sqlite schema so the
receipt rows can be asserted directly.

Run with:  pytest tests/regression_escrow.py
"""
from decimal import Decimal

from sqlmodel import select

from app.core.database import async_session_maker
from app.models.all_models import Job, User, Escrow, Receipt
from app.services.escrow_service import fund_escrow, mark_escrow_paid_by_reference


async def test_fund_escrow_no_duplicate_receipt_on_double_submit():
    async with async_session_maker() as db:
        job = Job(id=1, customer_id=2, description="CCTV install", status="booked")
        customer = User(id=2, email="c@t.com", hashed_password="x", role="customer", full_name="C", is_active=True)
        contractor = User(id=3, email="co@t.com", hashed_password="x", role="contractor", full_name="Co", is_active=True)
        db.add_all([job, customer, contractor])
        await db.commit()

        # First (legitimate) funding via a Paystack reference.
        escrow = await fund_escrow(
            db, job, customer, contractor, Decimal("150"), "Visa", "4242",
            paystack_reference="ref_abc",
        )
        await db.commit()

        # Duplicate submission (e.g. double-click + webhook) must NOT overwrite
        # the captured amount nor create a second receipt.
        escrow2 = await fund_escrow(
            db, job, customer, contractor, Decimal("999"), "Visa", "4242",
            paystack_reference="ref_abc",
        )
        await db.commit()

        assert escrow2.total_amount == Decimal("150"), "amount must not be overwritten"
        receipts = (
            await db.exec(select(Receipt).where(Receipt.payment_reference == "ref_abc"))
        ).all()
        assert len(receipts) == 1, "only one receipt per payment reference"


async def test_webhook_funding_is_idempotent_across_deliveries():
    async with async_session_maker() as db:
        job = Job(id=2, customer_id=4, description="CCTV repair", status="booked")
        customer = User(id=4, email="c2@t.com", hashed_password="x", role="customer", full_name="C2", is_active=True)
        contractor = User(id=5, email="co2@t.com", hashed_password="x", role="contractor", full_name="Co2", is_active=True)
        escrow = Escrow(
            job_id=2, customer_id=4, contractor_id=5, status="unfunded",
            quoted_amount=Decimal("200"), total_amount=Decimal("200"),
            platform_fee=Decimal("20"), contractor_payout=Decimal("180"),
            currency="NGN",
        )
        db.add_all([job, customer, contractor, escrow])
        await db.commit()

        meta = {"job_id": str(job.id)}
        # Two identical at-least-once webhook deliveries.
        await mark_escrow_paid_by_reference(
            db, "wf_xyz", amount=Decimal("200"), currency="NGN", metadata=meta,
        )
        await db.commit()
        await mark_escrow_paid_by_reference(
            db, "wf_xyz", amount=Decimal("200"), currency="NGN", metadata=meta,
        )
        await db.commit()

        receipts = (
            await db.exec(select(Receipt).where(Receipt.payment_reference == "wf_xyz"))
        ).all()
        assert len(receipts) == 1, "duplicate webhook delivery must not mint a second receipt"

        final = (await db.exec(select(Escrow).where(Escrow.job_id == 2))).first()
        assert final.status == "held"
