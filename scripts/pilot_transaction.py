"""Phase 6 — offline pilot transaction.

Proves the full funnel -> transaction loop without any paid provider:
free-tool lead -> contractor interest -> book -> fund escrow (mock) ->
complete -> release payout (mock) -> contractor wallet credited.

Run directly:  python scripts/pilot_transaction.py
Or import + call `run_pilot()` (used by the test suite).
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime
from decimal import Decimal

# Allow running both as a script and via pytest.
if __name__ == "__main__":
    sys.path.insert(0, ".")

from app.core.database import async_session_maker  # noqa: E402
from app.models.all_models import User, Job, Conversation  # noqa: E402
from app.services.escrow_service import create_escrow, fund_escrow, release_escrow  # noqa: E402


async def run_pilot() -> dict:
    async with async_session_maker() as db:
        ts = int(datetime.utcnow().timestamp())
        customer = User(
            email=f"pilot_cust_{ts}@example.com", hashed_password="x",
            role="customer", full_name="Pilot Customer",
        )
        contractor = User(
            email=f"pilot_cont_{ts}@example.com", hashed_password="x",
            role="contractor", full_name="Pilot Contractor",
            profession="plumbing", base_pricing=120.0, is_verified=True,
        )
        db.add_all([customer, contractor])
        await db.flush()

        # 1) Funnel lead: a customer creates an open job.
        job = Job(
            customer_id=customer.id, category="plumbing",
            description="Pilot: fix leaking pipe", status="open",
            brief={"source": "free_tool", "trade": "plumbing"},
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

        # 2) Contractor expresses interest (opens a chat channel).
        conv = Conversation(
            id=job.id, job_id=job.id, customer_id=customer.id, contractor_id=contractor.id,
        )
        db.add(conv)
        await db.commit()

        # 3) Customer books the contractor.
        job.assigned_contractor_id = contractor.id
        job.status = "booked"
        db.add(job)
        escrow = await create_escrow(db, job, customer, contractor, Decimal("120.00"))
        await db.commit()
        await db.refresh(escrow)

        # 4) Customer funds escrow (mock payment — no real gateway).
        escrow = await fund_escrow(
            db, job, customer, contractor, Decimal("120.00"),
            card_brand="visa", card_last4="4242",
        )
        await db.commit()
        await db.refresh(escrow)
        assert escrow.status == "held", escrow.status

        # 5) Work completed.
        job.status = "completed_pending"
        db.add(job)
        await db.commit()
        job.status = "completed"
        db.add(job)
        await db.commit()

        # 6) Release payout to the contractor (mock payout + wallet credit).
        escrow = await release_escrow(db, escrow)
        await db.commit()
        await db.refresh(escrow)

        return {
            "job_id": job.id,
            "escrow_status": escrow.status,
            "contractor_payout": float(escrow.contractor_payout),
            "platform_fee": float(escrow.platform_fee),
        }


if __name__ == "__main__":
    result = asyncio.run(run_pilot())
    print("Pilot transaction result:")
    for k, v in result.items():
        print(f"  {k}: {v}")
