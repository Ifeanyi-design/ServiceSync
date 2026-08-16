"""Phase 0 — security regression tests.

These lock in the hardening applied earlier (see docs/ROADMAP.md §3.1):
  * signup can never self-escalate to admin
  * only ``access`` tokens authenticate; refresh / 2fa_temp are rejected
  * banned (is_active=False) accounts are rejected even with a valid token
  * Paystack webhooks require a configured signing secret + valid HMAC

Run with:  pytest tests/regression_security.py
"""
import pytest
from fastapi import HTTPException

from app.core.config import settings
from app.core.security import create_access_token, create_refresh_token
from app.api.dependencies import get_current_user_optional
from app.api.v1.endpoints.auth import signup
from app.api.v1.endpoints.webhooks import paystack_webhook
from app.models.all_models import User
from app.schemas.user import UserCreate


async def _no_revoked(db, jti):
    """Stand-in for token revocation so the FakeDB doesn't report every lookup
    as a revoked token."""
    return False


class FakeRequest:
    def __init__(self, headers=None, cookies=None, body=b"{}"):
        self.headers = headers or {}
        self.cookies = cookies or {}
        self._body = body

    async def body(self):
        return self._body


class FakeDB:
    """Minimal async DB stand-in used by the unit-level service/auth tests."""

    def __init__(self, rows=None, user=None):
        self._rows = rows or []
        self._user = user
        self.added = []
        self.committed = 0

    async def exec(self, *args, **kwargs):
        class _Res:
            def first(self_inner):
                return self._user or (self._rows[0] if self._rows else None)

            def all(self_inner):
                return list(self._rows)

        return _Res()

    async def get(self, model, pk):
        return self._user

    def add(self, obj):
        self.added.append(obj)

    async def flush(self):
        pass

    async def commit(self):
        self.committed += 1

    async def refresh(self, obj):
        pass


# ── Signup privilege fix ─────────────────────────────────────────────────────
async def test_signup_coerces_admin_role_to_customer():
    payload = UserCreate(
        email="escalate@test.com",
        password="supersecret",
        role="admin",  # attacker tries to self-escalate
        full_name="Evil Admin",
    )
    created = await signup(payload, db=FakeDB())
    assert created.role == "customer", "signup must never grant admin"


async def test_signup_keeps_customer_role():
    payload = UserCreate(
        email="normal@test.com",
        password="supersecret",
        role="customer",
        full_name="Norm C",
    )
    created = await signup(payload, db=FakeDB())
    assert created.role == "customer"


# ── Token-type enforcement ──────────────────────────────────────────────────
async def test_refresh_token_rejected_as_access():
    refresh = create_refresh_token(subject=1)
    # No user lookup should even happen — non-access tokens are rejected up front.
    user = await get_current_user_optional(
        request=FakeRequest(), db=FakeDB(), token=refresh
    )
    assert user is None


async def test_2fa_temp_token_rejected_as_access():
    temp = create_access_token(subject=1, token_type="2fa_temp")
    user = await get_current_user_optional(
        request=FakeRequest(), db=FakeDB(), token=temp
    )
    assert user is None


async def test_valid_access_token_accepted_for_active_user(monkeypatch):
    monkeypatch.setattr("app.api.dependencies.is_token_revoked", _no_revoked)
    access = create_access_token(subject=42)
    db_user = User(
        id=42, email="a@b.com", hashed_password="x", role="customer",
        full_name="A", is_active=True,
    )
    user = await get_current_user_optional(
        request=FakeRequest(), db=FakeDB(user=db_user), token=access
    )
    assert user is not None and user.id == 42


async def test_banned_user_rejected_even_with_valid_token(monkeypatch):
    monkeypatch.setattr("app.api.dependencies.is_token_revoked", _no_revoked)
    access = create_access_token(subject=42)
    banned = User(
        id=42, email="a@b.com", hashed_password="x", role="customer",
        full_name="A", is_active=False,
    )
    user = await get_current_user_optional(
        request=FakeRequest(), db=FakeDB(user=banned), token=access
    )
    assert user is None


# ── Paystack webhook authentication ─────────────────────────────────────────
async def test_paystack_webhook_503_when_secret_unset():
    # Default config has no webhook secret — an unauthenticated webhook must be
    # refused so nobody can mark arbitrary escrows "held".
    settings.PAYSTACK_WEBHOOK_SECRET = None
    req = FakeRequest(headers={})
    with pytest.raises(HTTPException) as exc:
        await paystack_webhook(req, db=FakeDB())
    assert exc.value.status_code == 503


async def test_paystack_webhook_400_on_bad_signature(monkeypatch):
    settings.PAYSTACK_WEBHOOK_SECRET = "test-secret"
    body = b'{"event":"charge.success","data":{"reference":"x"}}'
    # Deliberately wrong signature.
    req = FakeRequest(
        headers={"x-paystack-signature": "deadbeef"},
        cookies={},
    )
    # Patch body() onto the request object.
    async def _body():
        return body
    req.body = _body
    try:
        with pytest.raises(HTTPException) as exc:
            await paystack_webhook(req, db=FakeDB())
        assert exc.value.status_code == 400
    finally:
        settings.PAYSTACK_WEBHOOK_SECRET = None
