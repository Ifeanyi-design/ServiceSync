"""Phase 2 — ServiceSync Voice (CALL-E) folded into the CCTV flow.

Verifies: (1) the CCTV brief is turned into a call-ready context for CALL-E;
(2) the voice dispatch endpoint targets the job's matched CCTV contractors
(when present) or an explicit contractor_ids list, and only falls back to a
global available pool when neither is set.
"""
from typing import Any

import pytest

from app.core.database import async_session_maker
from app.models.all_models import User, Job
from app.services import voice_dispatch
from app.api.v1.endpoints import voice as voice_router


# ── Unit: CCTV brief → CALL-E call context ─────────────────────────────────────
def test_brief_context_summarises_cctv():
    job = Job(
        customer_id=1, description="install cameras", category="cctv", status="open",
        brief={"category": "cctv", "cctv": {
            "site_type": "business", "camera_count": 4, "indoor_outdoor": "both",
            "key_features": ["night_vision"], "existing_wiring": "none",
            "internet_available": True, "budget_range": "mid", "urgency": "high",
        }},
    )
    ctx = voice_dispatch._brief_context(job)
    assert "cameras: 4" in ctx
    assert "night_vision" in ctx


def test_build_task_includes_brief():
    job = Job(
        customer_id=1, description="install cameras", category="cctv", status="open",
        brief={"category": "cctv", "cctv": {"camera_count": 2, "site_type": "home"}},
    )
    contractor = User(email="x@y.com", hashed_password="z", role="contractor", full_name="Cam Co", profession="cctv")
    task = voice_dispatch._build_task(job, contractor)
    assert "cameras: 2" in task
    assert "Cam Co" in task


# ── Integration: dispatch targets matched CCTV contractors ────────────────────
async def test_dispatch_uses_matched_contractor_ids(monkeypatch):
    captured = {}

    async def fake_dispatch(job, contractors):
        captured["job_id"] = job.id
        captured["contractor_ids"] = [c.id for c in contractors]
        return []

    monkeypatch.setattr(voice_router, "dispatch_calls", fake_dispatch)

    async with async_session_maker() as db:
        customer = User(email="c@y.com", hashed_password="z", role="customer", full_name="Cust")
        matched = User(email="m@y.com", hashed_password="z", role="contractor", full_name="Matched", profession="cctv")
        other = User(email="o@y.com", hashed_password="z", role="contractor", full_name="Other", profession="plumber", availability_status="Available")
        db.add_all([customer, matched, other])
        await db.flush()
        job = Job(customer_id=customer.id, description="cctv", category="cctv", status="open",
                  matched_contractor_ids=[matched.id])
        db.add(job)
        await db.flush()

        result = await voice_router.dispatch(job.id, contractor_ids=None, current_user=customer, db=db)
        assert result["dispatched"] == 0  # fake returns []
        assert captured["contractor_ids"] == [matched.id]
        assert other.id not in captured["contractor_ids"]


async def test_dispatch_falls_back_to_global_pool_when_no_match(monkeypatch):
    captured = {}

    async def fake_dispatch(job, contractors):
        captured["contractor_ids"] = [c.id for c in contractors]
        return []

    monkeypatch.setattr(voice_router, "dispatch_calls", fake_dispatch)

    async with async_session_maker() as db:
        customer = User(email="c2@y.com", hashed_password="z", role="customer", full_name="Cust")
        avail = User(email="a@y.com", hashed_password="z", role="contractor", full_name="Avail", availability_status="Available")
        busy = User(email="b@y.com", hashed_password="z", role="contractor", full_name="Busy", availability_status="Busy")
        db.add_all([customer, avail, busy])
        await db.flush()
        job = Job(customer_id=customer.id, description="general", category="general", status="open",
                  matched_contractor_ids=None)
        db.add(job)
        await db.flush()

        await voice_router.dispatch(job.id, contractor_ids=None, current_user=customer, db=db)
        assert avail.id in captured["contractor_ids"]
        assert busy.id not in captured["contractor_ids"]  # only "Available" pool
