from datetime import datetime, timezone, timedelta
import logging
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response, Cookie
from fastapi.security import OAuth2PasswordRequestForm
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import Any, Optional

from app.api.dependencies import get_db
from app.core.config import settings
from app.core.security import (
    get_password_hash, verify_password,
    create_access_token, create_refresh_token,
)
from app.models.all_models import User
from app.schemas.user import UserCreate, UserResponse, Token
from app.services.audit_service import log_audit
from app.services.token_service import (
    decode_token, revoke_token, is_token_revoked,
)
from app.services.account_service import (
    issue_email_verification, confirm_email,
    issue_password_reset, confirm_password_reset,
    issue_2fa_code, verify_2fa_code, admin_2fa_required,
)
from app.services.email_service import (
    send_verification_email, send_password_reset_email, send_2fa_code_email,
)

router = APIRouter()

logger = logging.getLogger("api.auth")

REFRESH_COOKIE = "refresh_token"


def _set_refresh_cookie(response: Response, refresh_token: str) -> None:
    response.set_cookie(
        key=REFRESH_COOKIE,
        value=refresh_token,
        httponly=True,
        secure=True,
        samesite="lax",
        max_age=60 * 60 * 24 * settings.REFRESH_TOKEN_EXPIRE_DAYS,
    )


@router.post("/signup", response_model=UserResponse)
async def signup(user_in: UserCreate, db: AsyncSession = Depends(get_db)) -> Any:
    result = await db.exec(select(User).where(User.email == user_in.email))
    if result.first():
        raise HTTPException(status_code=400, detail="The user with this email already exists in the system.")

    user_data = user_in.model_dump()
    user_data["hashed_password"] = get_password_hash(user_data.pop("password"))
    db_user = User(**user_data)
    if db_user.role == "contractor":
        from app.services.subscription_service import start_trial
        start_trial(db_user)
    db.add(db_user)
    await db.commit()
    await db.refresh(db_user)

    # Best-effort email verification (no-op if SMTP unconfigured).
    try:
        token = await issue_email_verification(db, db_user)
        await send_verification_email(db_user.email, token)
    except Exception:
        pass
    return db_user


@router.post("/login", response_model=Token)
async def login(
    response: Response,
    form_data: OAuth2PasswordRequestForm = Depends(),
    db: AsyncSession = Depends(get_db),
) -> Any:
    result = await db.exec(select(User).where(User.email == form_data.username))
    user = result.first()
    if not user or not verify_password(form_data.password, user.hashed_password):
        await log_audit(db, "login_failed", user_id=getattr(user, "id", None),
                        status="failure", detail=form_data.username)
        raise HTTPException(status_code=400, detail="Incorrect email or password")

    # Admin 2FA: issue a code + short-lived temp token instead of logging in.
    if admin_2fa_required(user):
        user.twofa_code = issue_2fa_code(user)
        await db.commit()
        logger.warning(
            "2FA code for %s: %s (expires in 10 min)",
            user.email, user.twofa_code,
        )
        try:
            await send_2fa_code_email(user.email, user.twofa_code)
        except Exception:
            pass
        temp_token = create_access_token(subject=user.id, token_type="2fa_temp",
                                         expires_delta=timedelta(minutes=10))
        return {"access_token": temp_token, "token_type": "2fa_required"}

    access = create_access_token(subject=user.id)
    refresh = create_refresh_token(subject=user.id)
    _set_refresh_cookie(response, refresh)
    await log_audit(db, "login_success", user_id=user.id, status="success")
    return {"access_token": access, "token_type": "bearer"}


@router.post("/2fa/verify", response_model=Token)
async def twofa_verify(
    response: Response,
    payload: dict,
    db: AsyncSession = Depends(get_db),
) -> Any:
    temp_token = payload.get("temp_token")
    code = payload.get("code")
    if not temp_token:
        raise HTTPException(status_code=400, detail="Missing temp token")
    try:
        data = decode_token(temp_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    if data.get("type") != "2fa_temp":
        raise HTTPException(status_code=401, detail="Invalid token type")
    user = (await db.exec(select(User).where(User.id == int(data["sub"])))).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    if not verify_2fa_code(user, code):
        await log_audit(db, "2fa_failed", user_id=user.id, status="failure")
        raise HTTPException(status_code=400, detail="Invalid or expired code")
    await db.commit()
    await log_audit(db, "2fa_success", user_id=user.id, status="success")
    access = create_access_token(subject=user.id)
    refresh = create_refresh_token(subject=user.id)
    _set_refresh_cookie(response, refresh)
    return {"access_token": access, "token_type": "bearer"}


@router.get("/verify-email")
async def verify_email(token: str, db: AsyncSession = Depends(get_db)):
    ok = await confirm_email(db, token)
    return {"verified": ok}


@router.post("/forgot-password")
async def forgot_password(email: str, db: AsyncSession = Depends(get_db)):
    user = await issue_password_reset(db, email)
    if user:
        try:
            await send_password_reset_email(user.email, user.reset_token)
        except Exception:
            pass
    # Always return the same response to avoid account enumeration.
    return {"detail": "If that email exists, a reset link has been sent."}


@router.post("/reset-password")
async def reset_password(token: str, new_password: str, db: AsyncSession = Depends(get_db)):
    ok = await confirm_password_reset(db, token, new_password)
    if not ok:
        raise HTTPException(status_code=400, detail="Invalid or expired reset token")
    return {"detail": "Password updated successfully."}


@router.post("/refresh", response_model=Token)
async def refresh(
    response: Response,
    refresh_token: Optional[str] = Cookie(default=None),
    db: AsyncSession = Depends(get_db),
) -> Any:
    if not refresh_token:
        raise HTTPException(status_code=401, detail="Missing refresh token")
    try:
        data = decode_token(refresh_token)
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid refresh token")
    if data.get("type") != "refresh":
        raise HTTPException(status_code=401, detail="Invalid token type")
    jti = data.get("jti")
    if jti and await is_token_revoked(db, jti):
        raise HTTPException(status_code=401, detail="Refresh token revoked")
    user = (await db.exec(select(User).where(User.id == int(data["sub"])))).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    access = create_access_token(subject=user.id)
    # Rotate refresh token for basic reuse protection.
    new_refresh = create_refresh_token(subject=user.id)
    await revoke_token(db, jti, datetime.fromtimestamp(data["exp"], tz=timezone.utc), reason="refresh_rotate")
    _set_refresh_cookie(response, new_refresh)
    return {"access_token": access, "token_type": "bearer"}


@router.post("/logout")
async def logout(
    response: Response,
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    # Revoke the access token (and refresh, if present) by jti.
    auth = request.headers.get("Authorization", "")
    access = auth.replace("Bearer ", "", 1) if auth.startswith("Bearer ") else None
    refresh = request.cookies.get(REFRESH_COOKIE)
    for tok in (access, refresh):
        if tok:
            try:
                data = decode_token(tok)
                jti = data.get("jti")
                if jti:
                    await revoke_token(db, jti, datetime.fromtimestamp(data["exp"], tz=timezone.utc), reason="logout")
            except Exception:
                pass
    response.delete_cookie(REFRESH_COOKIE, secure=True, httponly=True, samesite="lax")
    return {"detail": "Logged out"}
