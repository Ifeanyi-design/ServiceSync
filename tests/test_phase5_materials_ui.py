"""Phase 5: contractor-facing Materials board UI (procurement loop closed)."""
from fastapi.testclient import TestClient

from app.main import app
from app.core.database import async_session_maker
from app.models.all_models import User, Job, MaterialOrder
from sqlmodel import select


def _signup_login(client, email, password, role, profession=None):
    payload = {"email": email, "password": password, "full_name": "Test", "role": role}
    if profession:
        payload["profession"] = profession
    client.post("/api/v1/auth/signup", json=payload)
    r = client.post("/api/v1/auth/login", data={"username": email, "password": password})
    token = r.json().get("access_token")
    client.cookies.set("access_token", token)


def test_materials_page_requires_auth():
    client = TestClient(app)
    r = client.get("/materials")
    assert r.status_code in (401, 403, 302, 307)


def test_materials_page_contractor_ok():
    client = TestClient(app)
    _signup_login(client, "matcontractor@example.com", "ContractorPass123", "contractor", "plumbing")
    r = client.get("/materials")
    assert r.status_code == 200
    assert "Materials Board" in r.text


async def test_materials_page_order_and_deliver_flow():
    client = TestClient(app)
    # contractor (will be logged in) + customer, both via the real signup (proper hashes)
    client.post("/api/v1/auth/signup", json={"email": "c1@example.com", "password": "Pass123!", "full_name": "C", "role": "contractor", "profession": "plumbing"})
    r = client.post("/api/v1/auth/login", data={"username": "c1@example.com", "password": "Pass123!"})
    client.cookies.set("access_token", r.json()["access_token"])
    client.post("/api/v1/auth/signup", json={"email": "cu1@example.com", "password": "Pass123!", "full_name": "U", "role": "customer"})

    async with async_session_maker() as db:
        contractor = (await db.exec(select(User).where(User.email == "c1@example.com"))).first()
        customer = (await db.exec(select(User).where(User.email == "cu1@example.com"))).first()
        job = Job(customer_id=customer.id, assigned_contractor_id=contractor.id, description="Install cameras", category="cctv")
        db.add(job)
        await db.commit()
        await db.refresh(job)
        job_id = job.id

    r = client.get("/materials")
    assert r.status_code == 200
    assert "Order materials" in r.text

    r = client.post(f"/api/v1/suppliers/jobs/{job_id}/order", json={})
    assert r.status_code == 200
    assert r.json()["status"] == "ordered"

    r = client.get("/materials")
    assert "Mark delivered" in r.text

    async with async_session_maker() as db:
        order = (await db.exec(select(MaterialOrder).where(MaterialOrder.job_id == job_id))).first()
        order_id = order.id

    r = client.post(f"/api/v1/suppliers/orders/{order_id}/fulfill")
    assert r.status_code == 200

    r = client.get("/materials")
    assert "delivered" in r.text
