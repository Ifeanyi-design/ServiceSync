"""JWT helpers: jti generation, DB-backed revocation, and token decode with
revocation checks. Keeps ``app.core.security`` free of DB imports.
"""
import secrets
import uuid
from datetime import datetime, timezone
from typing import Optional

import jwt
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.all_models import RevokedToken


def generate_jti() -> str:
    return uuid.uuid4().hex


def decode_token(token: str) -> dict:
    return jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])


async def revoke_token(db: AsyncSession, jti: str, expires_at: datetime,
                       reason: Optional[str] = None) -> None:
    if await _is_revoked(db, jti):
        return
    db.add(RevokedToken(jti=jti, expires_at=expires_at, reason=reason))
    await db.commit()


async def _is_revoked(db: AsyncSession, jti: str) -> bool:
    res = await db.exec(select(RevokedToken).where(RevokedToken.jti == jti))
    return res.first() is not None


async def is_token_revoked(db: AsyncSession, jti: str) -> bool:
    return await _is_revoked(db, jti)


def new_code(length: int = 6) -> str:
    """Numeric one-time code for admin 2FA."""
    return "".join(secrets.choice("0123456789") for _ in range(length))
