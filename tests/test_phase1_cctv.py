"""Phase 1 — CCTV vertical tests.

Covers the AI intake + quote services (with a fake, offline provider) and the
end-to-end intake endpoint (job creation + CCTV contractor matching + quote
drafting) using the real async DB session.
"""
import json
from typing import Any

import pytest

from app.core.database import async_session_maker
from app.models.all_models import User, Job
from app.services.intake_service import intake_job, JobBrief, CCTVJobBrief
from app.services.quote_service import draft_quote, JobQuote
from app.api.v1.endpoints import cctv as cctv_router


class FakeProvider:
    """Offline stand-in for an LLM provider — returns fixed JSON."""

    def __init__(self, payload: dict):
        self.payload = payload

    async def complete(self, prompt: str, json_mode: bool = False, temperature: float = 0.7) -> str:
        return json.dumps(self.payload)


# ── Unit: intake service ──────────────────────────────────────────────────────
async def test_intake_job_high_confidence_with_provider():
    provider = FakeProvider({
        "site_type": "business",
        "camera_count": 4,
        "indoor_outdoor": "both",
        "key_features": ["night_vision", "remote_viewing"],
        "existing_wiring": "none",
        "internet_available": True,
        "budget_range": "mid",
        "urgency": "medium",
        "notes": "shop front",
    })
    brief = await intake_job("4 cameras for my shop", "cctv", provider=provider)
    assert isinstance(brief, JobBrief)
    assert brief.confidence == "high"
    assert brief.cctv is not None
    assert brief.cctv.camera_count == 4
    assert "night_vision" in brief.cctv.key_features


async def test_intake_job_offline_fallback():
    class Boom:
        async def complete(self, *a, **k):
            raise RuntimeError("no model")

    brief = await intake_job("anything", "cctv", provider=Boom())
    assert brief.confidence == "low"
    assert brief.requires_review is True


# ── Unit: quote service ────────────────────────────────────────────────────────
async def test_draft_quote_with_provider():
    contractor = User(
        email="c@x.com", hashed_password="x", role="contractor",
        full_name="Cam Pro", profession="cctv", base_pricing=80.0,
    )
    provider = FakeProvider({
        "line_items": [
            {"description": "4x camera install", "qty": 4, "unit_price": 60, "total": 240},
        ],
        "labor_total": 120, "materials_total": 240, "total_estimate": 360,
        "currency": "USD", "assumptions": ["access ok"], "notes": "ok",
    })
    quote = await draft_quote({"camera_count": 4}, contractor, "cctv", provider=provider)
    assert isinstance(quote, JobQuote)
    assert quote.confidence == "high"
    assert quote.total_estimate == 360
    assert len(quote.line_items) == 1


async def test_draft_quote_offline_fallback():
    contractor = User(
        email="c2@x.com", hashed_password="x", role="contractor",
        full_name="Cam Pro 2", profession="cctv",
    )
    class Boom:
        async def complete(self, *a, **k):
            raise RuntimeError("no model")
    quote = await draft_quote({}, contractor, "cctv", provider=Boom())
    assert quote.confidence == "low"
    assert "manual quote" in quote.notes.lower()


# ── Integration: intake endpoint → job + matched contractor + quote ────────────
async def test_cctv_intake_endpoint_creates_job_and_matches(monkeypatch):
    monkeypatch.setattr(
        cctv_router, "intake_job",
        lambda description, category="cctv": intake_job(
            description, category, provider=FakeProvider({
                "site_type": "home", "camera_count": 2, "indoor_outdoor": "both",
                "key_features": ["night_vision"], "existing_wiring": "none",
                "internet_available": True, "budget_range": "low",
                "urgency": "low", "notes": "",
            })
        )
    )
    monkeypatch.setattr(
        cctv_router, "draft_quote",
        lambda brief, contractor, category="cctv": draft_quote(
            brief, contractor, category, provider=FakeProvider({
                "line_items": [], "total_estimate": 150, "currency": "USD",
                "assumptions": [], "notes": "ok",
            })
        )
    )

    async with async_session_maker() as db:
        customer = User(
            email="cust@x.com", hashed_password="x", role="customer", full_name="Cust"
        )
        contractor = User(
            email="inst@x.com", hashed_password="x", role="contractor",
            full_name="Installer", profession="cctv",
            specialties=["cctv"], city="Lagos", availability_status="Available",
        )
        db.add(customer); db.add(contractor)
        await db.flush()

        req = cctv_router.IntakeRequest(
            description="2 cameras at home", category="cctv", city="Lagos"
        )
        result = await cctv_router.cctv_intake(req, customer, db)
        assert result["job_id"]
        assert result["brief"]["confidence"] == "high"
        matched = result["contractors"]
        assert matched and matched[0]["profession"] == "cctv"

        job = await db.get(Job, result["job_id"])
        assert job is not None and job.category == "cctv" and job.status == "open"

        quote = await cctv_router.draft_quote_endpoint(job.id, contractor, db)
        assert quote["category"] == "cctv"
        assert quote["total_estimate"] == 150
