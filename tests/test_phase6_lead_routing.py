"""Phase 6 — lead routing (match contractors, notify, express interest, pilot)."""
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import async_session_maker
from app.models.all_models import User, Job, Conversation
from app.services.lead_service import match_contractors_for_job, open_leads_for_contractor
from sqlmodel import select


async def _seed():
    async with async_session_maker() as db:
        customer = User(email="leadc@example.com", hashed_password="x", role="customer", full_name="C")
        plumber = User(email="leadp@example.com", hashed_password="x", role="contractor", full_name="P", profession="plumbing")
        painter = User(email="leadt@example.com", hashed_password="x", role="contractor", full_name="T", profession="painting")
        db.add_all([customer, plumber, painter])
        await db.flush()
        job = Job(customer_id=customer.id, category="plumbing", description="Leak", status="open")
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return customer.id, plumber.id, painter.id, job.id


async def test_match_and_open_leads():
    customer_id, plumber_id, painter_id, job_id = await _seed()
    async with async_session_maker() as db:
        job = await db.get(Job, job_id)
        matches = await match_contractors_for_job(db, job)
        match_ids = {u.id for u in matches}
        assert plumber_id in match_ids
        assert painter_id not in match_ids

        plumber = await db.get(User, plumber_id)
        leads = await open_leads_for_contractor(db, plumber)
        assert any(j.id == job_id for j in leads)


def _login(client, email, password):
    client.post("/api/v1/auth/signup", json={"email": email, "password": password, "full_name": "X", "role": "contractor", "profession": "plumbing"})


def test_express_interest_creates_conversation():
    client = TestClient(app)
    # customer + open job (use request-pro to mimic the funnel)
    client.post("/api/v1/auth/signup", json={"email": "intc@example.com", "password": "Pass123!", "full_name": "C", "role": "customer"})
    r = client.post("/api/v1/auth/login", data={"username": "intc@example.com", "password": "Pass123!"})
    client.cookies.set("access_token", r.json()["access_token"])
    r = client.get("/tools/request-pro?trade=plumbing&redirect=/contractors", follow_redirects=False)
    # extract job id from redirect? Instead create directly via API is not exposed; use DB.
    import asyncio
    from app.core.database import async_session_maker
    from app.models.all_models import User, Job

    async def get_job():
        async with async_session_maker() as db:
            c = (await db.exec(select(User).where(User.email == "intc@example.com"))).first()
            j = (await db.exec(select(Job).where(Job.customer_id == c.id))).first()
            return j.id

    job_id = asyncio.run(get_job())

    # contractor logs in and expresses interest
    client2 = TestClient(app)
    _login(client2, "intp@example.com", "Pass123!")
    r = client2.post("/api/v1/auth/login", data={"username": "intp@example.com", "password": "Pass123!"})
    client2.cookies.set("access_token", r.json()["access_token"])
    resp = client2.post(f"/api/v1/jobs/{job_id}/interest")
    assert resp.status_code == 200
    assert "/chat/" in resp.json()["chat_url"]

    # leads board now shows the conversation open
    r = client2.get("/leads")
    assert r.status_code == 200
    assert "Open chat" in r.text


def test_leads_page_requires_contractor():
    client = TestClient(app)
    client.post("/api/v1/auth/signup", json={"email": "leadg@example.com", "password": "Pass123!", "full_name": "C", "role": "customer"})
    r = client.post("/api/v1/auth/login", data={"username": "leadg@example.com", "password": "Pass123!"})
    client.cookies.set("access_token", r.json()["access_token"])
    resp = client.get("/leads")
    assert resp.status_code in (403, 401)
