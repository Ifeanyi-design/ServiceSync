"""Smoke tests — fast, no live database required.

These verify the app builds, routes are registered, and the core money/state
logic behaves correctly. They rely only on in-memory objects and mocks.
"""
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient


def test_app_imports():
    import app.main  # noqa: F401
    assert app.main.app is not None


def test_health_route():
    from app.main import app
    with TestClient(app) as client:
        r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_core_routes_registered():
    from app.main import app
    schema = app.openapi()
    paths = set(schema.get("paths", {}).keys())
    # HTML pages + API
    assert "/health" in paths
    assert "/auth/login" in paths
    assert "/admin" in paths
    assert "/escrow/{job_id}/fund" in paths
    assert any(p.startswith("/api/v1/jobs") for p in paths)
    assert any(p.startswith("/api/v1/escrow") for p in paths)


@pytest.mark.asyncio
async def test_upload_local_fallback(tmp_path, monkeypatch):
    """Without Cloudinary/S3 configured the helper stores locally and returns
    a /static/uploads URL."""
    import app.services.upload_service as us
    monkeypatch.setattr(us, "LOCAL_UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(us, "settings", type("S", (), {
        "CLOUDINARY_URL": None, "CLOUDINARY_API_KEY": None,
        "CLOUDINARY_CLOUD_NAME": None, "AWS_S3_BUCKET": None,
    })())
    from app.services.upload_service import save_upload
    url = await save_upload(b"hello", "doc.pdf", allowlist={".pdf"}, max_bytes=1024)
    assert url.startswith("/static/uploads/")
    name = url.split("/")[-1]
    assert (tmp_path / name).read_bytes() == b"hello"


@pytest.mark.asyncio
async def test_upload_rejects_bad_type():
    from app.services.upload_service import save_upload
    with pytest.raises(ValueError):
        await save_upload(b"x", "evil.exe", allowlist={".pdf"}, max_bytes=1024)


def test_broadcast_hub_memory_fallback(monkeypatch):
    """With no REDIS_URL, publish delivers to the local deliverer only."""
    import app.services.broadcast_hub as hub
    monkeypatch.setattr(hub.settings, "REDIS_URL", None)
    received = {}

    async def deliverer(cid, message, exclude=None):
        received[cid] = message

    hub.register_local_deliverer(deliverer)
    import asyncio
    asyncio.run(hub.publish(7, "hi"))
    assert received.get(7) == "hi"


class FakeDB:
    """Minimal async DB stand-in for unit-testing service flows."""
    def __init__(self, rows=None):
        self._rows = rows or []
        self.added = []
        self.flushed = 0

    async def exec(self, *args, **kwargs):
        class _Res:
            def first(self_inner): return self._rows[0] if self._rows else None
            def all(self_inner): return list(self._rows)
        return _Res()

    async def get(self, model, pk):
        return None

    def add(self, obj): self.added.append(obj)
    async def flush(self): self.flushed += 1
    async def commit(self): pass
    async def refresh(self, obj): pass


@pytest.mark.asyncio
async def test_escrow_cannot_force_release_disputed():
    from app.services.escrow_service import release_escrow
    from app.models.all_models import Escrow
    escrow = Escrow(job_id=1, customer_id=2, contractor_id=3, status="disputed")
    db = FakeDB()
    with pytest.raises(ValueError):
        await release_escrow(db, escrow)


@pytest.mark.asyncio
async def test_escrow_penalty_split_allowed_from_disputed():
    from app.services.escrow_service import penalty_split_escrow
    from app.models.all_models import Escrow
    escrow = Escrow(
        job_id=1, customer_id=2, contractor_id=3, status="disputed",
        total_amount=100,
    )
    db = FakeDB()
    result = await penalty_split_escrow(db, escrow)
    assert result.status == "penalty_split"
    assert result.contractor_payout == 20
    assert result.customer_refund == 80


@pytest.mark.asyncio
async def test_fund_escrow_idempotent_when_held():
    from app.services.escrow_service import fund_escrow
    from app.models.all_models import Escrow, Job
    job = Job(id=1, status="booked", customer_id=2, assigned_contractor_id=3)
    escrow = Escrow(job_id=1, customer_id=2, contractor_id=3, status="held",
                    total_amount=50, quoted_amount=50)
    db = FakeDB(rows=[escrow])
    result = await fund_escrow(db, job, MagicMock(), MagicMock(), 999, "Visa", "4242")
    # Amount must NOT be overwritten by a second (duplicate) funding.
    assert result.total_amount == 50
    # No further DB writes should have happened for an already-held escrow.
    assert db.flushed == 0


@pytest.mark.asyncio
async def test_upload_rejects_spoofed_extension(tmp_path, monkeypatch):
    """A .png file whose bytes are NOT a PNG must be rejected (content sniff)."""
    import app.services.upload_service as us
    monkeypatch.setattr(us, "LOCAL_UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(us, "settings", type("S", (), {
        "CLOUDINARY_URL": None, "CLOUDINARY_API_KEY": None,
        "CLOUDINARY_CLOUD_NAME": None, "AWS_S3_BUCKET": None,
    })())
    from app.services.upload_service import save_upload
    with pytest.raises(ValueError):
        await save_upload(b"\x00\x01\x02\x03not an image", "trap.png",
                          allowlist={".png"}, max_bytes=1024)


@pytest.mark.asyncio
async def test_upload_accepts_real_png(tmp_path, monkeypatch):
    import app.services.upload_service as us
    monkeypatch.setattr(us, "LOCAL_UPLOAD_DIR", tmp_path)
    monkeypatch.setattr(us, "settings", type("S", (), {
        "CLOUDINARY_URL": None, "CLOUDINARY_API_KEY": None,
        "CLOUDINARY_CLOUD_NAME": None, "AWS_S3_BUCKET": None,
    })())
    from app.services.upload_service import save_upload
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
    url = await save_upload(png, "ok.png", allowlist={".png"}, max_bytes=1024)
    assert url.startswith("/static/uploads/")
