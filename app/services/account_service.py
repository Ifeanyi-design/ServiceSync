"""Shared account flows: email verification, password reset, admin 2FA.

Used by both the JSON API (app/api/v1/endpoints/auth.py) and the server-rendered
web pages (app/web/auth_pages.py) so the logic lives in exactly one place.
"""
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.all_models import User
from app.core.config import settings


def _now() -> datetime:
    return datetime.utcnow()


def _token() -> str:
    return secrets.token_urlsafe(32)


async def issue_email_verification(db: AsyncSession, user: User) -> str:
    user.email_verify_token = _token()
    user.email_verify_expiry = _now() + timedelta(hours=24)
    db.add(user)
    await db.commit()
    return user.email_verify_token


async def confirm_email(db: AsyncSession, token: str) -> bool:
    if not token:
        return False
    res = await db.exec(select(User).where(User.email_verify_token == token))
    user = res.first()
    if not user or not user.email_verify_expiry or user.email_verify_expiry < _now():
        return False
    user.email_verified = True
    user.email_verify_token = None
    user.email_verify_expiry = None
    db.add(user)
    await db.commit()
    return True


async def issue_password_reset(db: AsyncSession, email: str) -> Optional[User]:
    res = await db.exec(select(User).where(User.email == email))
    user = res.first()
    if not user:
        return None
    user.reset_token = _token()
    user.reset_token_expiry = _now() + timedelta(hours=1)
    db.add(user)
    await db.commit()
    return user


async def confirm_password_reset(db: AsyncSession, token: str, new_password: str) -> bool:
    if not token or len(new_password) < 8:
        return False
    res = await db.exec(select(User).where(User.reset_token == token))
    user = res.first()
    if not user or not user.reset_token_expiry or user.reset_token_expiry < _now():
        return False
    from app.core.security import get_password_hash
    user.hashed_password = get_password_hash(new_password)
    user.reset_token = None
    user.reset_token_expiry = None
    db.add(user)
    await db.commit()
    return True


def issue_2fa_code(user: User) -> str:
    from app.services.token_service import new_code
    user.twofa_code = new_code()
    user.twofa_expiry = _now() + timedelta(minutes=10)
    return user.twofa_code


def verify_2fa_code(user: User, code: str) -> bool:
    if not user.twofa_code or not user.twofa_expiry:
        return False
    if user.twofa_expiry < _now():
        user.twofa_code = None
        return False
    ok = secrets.compare_digest(user.twofa_code, (code or "").strip())
    if ok:
        user.twofa_code = None
        user.twofa_expiry = None
    return ok


def admin_2fa_required(user: User) -> bool:
    return user.role == "admin" and (
        settings.ADMIN_2FA_REQUIRED or user.twofa_enabled
    )
