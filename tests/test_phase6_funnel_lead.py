"""Phase 6 — funnel -> real Job lead conversion."""
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import async_session_maker
from app.models.all_models import User, Job
from sqlmodel import select


def _signup_login(client, email, password, role, profession=None):
    payload = {"email": email, "password": password, "full_name": "Test", "role": role}
    if profession:
        payload["profession"] = profession
    client.post("/api/v1/auth/signup", json=payload)
    r = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    client.cookies.set("access_token", r.json()["access_token"])


def test_request_pro_redirects_guest():
    client = TestClient(app)
    r = client.get("/tools/request-pro?trade=plumbing&redirect=/contractors?profession=plumbing",
                   follow_redirects=False)
    assert r.status_code in (302, 307)
    assert "/auth/signup" in r.headers["location"]


async def test_request_pro_creates_job_for_customer():
    client = TestClient(app)
    _signup_login(client, "leadc@example.com", "Pass123!", "customer")
    r = client.get("/tools/request-pro?trade=hvac&redirect=/contractors?profession=hvac",
                   follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"].startswith("/contractors")

    async with async_session_maker() as db:
        cust = (await db.exec(select(User).where(User.email == "leadc@example.com"))).first()
        job = (await db.exec(select(Job).where(Job.customer_id == cust.id))).first()
        assert job is not None
        assert job.category == "hvac"
        assert job.status == "open"
        assert job.brief.get("source") == "free_tool"
