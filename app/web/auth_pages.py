from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from app.api.dependencies import get_db, get_current_user_optional
from app.core.security import verify_password, create_access_token, create_refresh_token, get_password_hash
from app.core.config import settings
from app.models.all_models import User
from app.services.token_service import decode_token, revoke_token
from app.services.account_service import (
    issue_email_verification, confirm_email, issue_password_reset,
    confirm_password_reset, issue_2fa_code, verify_2fa_code, admin_2fa_required,
)
from app.services.email_service import (
    send_verification_email, send_password_reset_email, send_2fa_code_email,
)
from datetime import datetime, timezone, timedelta

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter(prefix="/auth")


# ─────────────────────────────────────────────
#  GET  /auth/login
# ─────────────────────────────────────────────
@router.get("/login", response_class=HTMLResponse)
async def login_page(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional),
    error: Optional[str] = None,
    next: Optional[str] = "/",
):
    if current_user:
        return RedirectResponse(url=_dashboard_url(current_user))
    contractor_id = _contractor_id_from_next(next)
    return templates.TemplateResponse(request=request, name="login.html", context={
        "request": request,
        "current_user": None,
        "error": error,
        "next": next,
        "contractor_id": contractor_id,
    })


# ─────────────────────────────────────────────
#  POST /auth/login  — sets HTTP-only cookie
# ─────────────────────────────────────────────
@router.post("/login", response_class=HTMLResponse)
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
    next: str = Form(default="/"),
    contractor_id: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    result = await db.exec(select(User).where(User.email == email))
    user = result.first()

    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse(request=request, name="login.html", context={
            "request": request,
            "current_user": None,
            "error": "Incorrect email or password. Please try again.",
            "next": next,
            "contractor_id": contractor_id or _contractor_id_from_next(next),
        }, status_code=400)

    # Admin 2FA: send a code and defer the session until the code is entered.
    if admin_2fa_required(user):
        user.twofa_code = issue_2fa_code(user)
        await db.commit()
        try:
            await send_2fa_code_email(user.email, user.twofa_code)
        except Exception:
            pass
        temp = create_access_token(subject=user.id, token_type="2fa_temp",
                                   expires_delta=timedelta(minutes=10))
        response = RedirectResponse(url="/auth/2fa", status_code=302)
        response.set_cookie(key="twofa_temp", value=temp, httponly=True,
                            secure=True, samesite="lax", max_age=600)
        return response

    token = create_access_token(subject=user.id)
    redirect_url = _post_auth_redirect_url(user, next, contractor_id)
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=60 * 60 * 24 * 7,  # 7 days
    )
    return response


# ─────────────────────────────────────────────
#  GET  /auth/signup
# ─────────────────────────────────────────────
@router.get("/signup", response_class=HTMLResponse)
async def signup_page(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional),
    error: Optional[str] = None,
    next: Optional[str] = "/",
):
    if current_user:
        return RedirectResponse(url=_dashboard_url(current_user))
    contractor_id = _contractor_id_from_next(next)
    return templates.TemplateResponse(request=request, name="signup.html", context={
        "request": request,
        "current_user": None,
        "error": error,
        "next": next,
        "contractor_id": contractor_id,
    })


# ─────────────────────────────────────────────
#  POST /auth/signup — creates account + sets cookie
# ─────────────────────────────────────────────
@router.post("/signup", response_class=HTMLResponse)
async def signup_submit(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    role: str = Form(default="customer"),
    next: str = Form(default="/"),
    contractor_id: Optional[str] = Form(default=None),
    db: AsyncSession = Depends(get_db),
):
    # Validate role
    if role not in ("customer", "contractor"):
        role = "customer"

    # Password strength policy (mirrors API signup).
    if len(password) < 8:
        return templates.TemplateResponse(request=request, name="signup.html", context={
            "request": request,
            "current_user": None,
            "error": "Password must be at least 8 characters.",
            "next": next,
            "contractor_id": contractor_id or _contractor_id_from_next(next),
        }, status_code=400)

    # Check duplicate
    result = await db.exec(select(User).where(User.email == email))
    if result.first():
        return templates.TemplateResponse(request=request, name="signup.html", context={
            "request": request,
            "current_user": None,
            "error": "An account with that email already exists.",
            "next": next,
            "contractor_id": contractor_id or _contractor_id_from_next(next),
        }, status_code=400)

    user = User(
        email=email,
        full_name=full_name,
        hashed_password=get_password_hash(password),
        role=role,
    )
    # New contractors get a 14-day premium trial
    if role == "contractor":
        from app.services.subscription_service import start_trial
        start_trial(user)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    # Best-effort verification email (no-op if SMTP unconfigured).
    try:
        vtoken = await issue_email_verification(db, user)
        await send_verification_email(user.email, vtoken)
    except Exception:
        pass

    token = create_access_token(subject=user.id)
    redirect_url = _post_auth_redirect_url(user, next, contractor_id)
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=60 * 60 * 24 * 7,
    )
    return response


# ─────────────────────────────────────────────
#  GET  /auth/register_contractor
# ─────────────────────────────────────────────
@router.get("/register_contractor", response_class=HTMLResponse)
async def register_contractor_page(
    request: Request,
    current_user: Optional[User] = Depends(get_current_user_optional),
    error: Optional[str] = None,
):
    if current_user:
        return RedirectResponse(url=_dashboard_url(current_user))
    return templates.TemplateResponse(request=request, name="register_contractor.html", context={
        "request": request,
        "current_user": None,
        "error": error,
    })


# ─────────────────────────────────────────────
#  POST /auth/register_contractor
# ─────────────────────────────────────────────
@router.post("/register_contractor", response_class=HTMLResponse)
async def register_contractor_submit(
    request: Request,
    full_name: str = Form(...),
    email: str = Form(...),
    password: str = Form(...),
    profession: str = Form(...),
    zip_code: Optional[str] = Form(default=None),
    country: Optional[str] = Form(default=None),
    state_or_province: Optional[str] = Form(default=None),
    city: Optional[str] = Form(default=None),
    area: Optional[str] = Form(default=None),
    postal_code: Optional[str] = Form(default=None),
    latitude: Optional[float] = Form(default=None),
    longitude: Optional[float] = Form(default=None),
    base_pricing: float = Form(default=0.0),
    service_radius_miles: int = Form(default=25),
    max_daily_jobs: int = Form(default=4),
    ai_tone_preference: str = Form(default="professional"),
    trade_qualifications: str = Form(default="{}"),
    db: AsyncSession = Depends(get_db),
):
    import json

    # Password strength policy.
    if len(password) < 8:
        return templates.TemplateResponse(request=request, name="register_contractor.html", context={
            "request": request,
            "current_user": None,
            "error": "Password must be at least 8 characters.",
        }, status_code=400)

    # Parse the JSON string from the frontend hidden input
    try:
        qualifications_dict = json.loads(trade_qualifications)
    except:
        qualifications_dict = {}

    # Check duplicate
    result = await db.exec(select(User).where(User.email == email))
    if result.first():
        return templates.TemplateResponse(request=request, name="register_contractor.html", context={
            "request": request,
            "current_user": None,
            "error": "An account with that email already exists.",
        }, status_code=400)

    user = User(
        email=email,
        full_name=full_name,
        hashed_password=get_password_hash(password),
        role="contractor",
        profession=profession,
        zip_code=zip_code,
        country=country,
        state_or_province=state_or_province,
        city=city,
        area=area,
        postal_code=postal_code,
        latitude=latitude,
        longitude=longitude,
        base_pricing=base_pricing,
        service_radius_miles=service_radius_miles,
        max_daily_jobs=max_daily_jobs,
        ai_tone_preference=ai_tone_preference,
        trade_qualifications=qualifications_dict,
    )
    # New contractors get a 14-day premium trial
    from app.services.subscription_service import start_trial
    start_trial(user)
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(subject=user.id)
    response = RedirectResponse(url="/dashboard/contractor", status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=True,
        max_age=60 * 60 * 24 * 7,
    )
    return response


# ─────────────────────────────────────────────
#  GET  /auth/logout — clears cookie
# ─────────────────────────────────────────────
@router.get("/logout")
async def logout(request: Request, db: AsyncSession = Depends(get_db)):
    cookie = request.cookies.get("access_token")
    if cookie:
        try:
            data = decode_token(cookie)
            jti = data.get("jti")
            if jti:
                await revoke_token(db, jti, datetime.fromtimestamp(data["exp"], tz=timezone.utc), reason="logout")
        except Exception:
            pass
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("access_token", secure=True, httponly=True, samesite="lax")
    return response


# ─────────────────────────────────────────────
#  Admin 2FA step (web)
# ─────────────────────────────────────────────
@router.get("/2fa", response_class=HTMLResponse)
async def twofa_page(request: Request, error: Optional[str] = None):
    temp = request.cookies.get("twofa_temp")
    if not temp:
        return RedirectResponse(url="/auth/login", status_code=302)
    return HTMLResponse(_twofa_html(error=error))


@router.post("/2fa", response_class=HTMLResponse)
async def twofa_submit(
    request: Request,
    code: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    temp = request.cookies.get("twofa_temp")
    if not temp:
        return RedirectResponse(url="/auth/login", status_code=302)
    try:
        data = decode_token(temp)
    except Exception:
        return RedirectResponse(url="/auth/login", status_code=302)
    if data.get("type") != "2fa_temp":
        return RedirectResponse(url="/auth/login", status_code=302)
    user = (await db.exec(select(User).where(User.id == int(data["sub"])))).first()
    if not user or not verify_2fa_code(user, code):
        return HTMLResponse(_twofa_html(error="Invalid or expired code."), status_code=400)
    await db.commit()
    token = create_access_token(subject=user.id)
    response = RedirectResponse(url=_dashboard_url(user), status_code=302)
    response.set_cookie(key="access_token", value=token, httponly=True,
                        samesite="lax", secure=True, max_age=60 * 60 * 24 * 7)
    response.delete_cookie("twofa_temp", secure=True, httponly=True, samesite="lax")
    return response


# ─────────────────────────────────────────────
#  Email verification (web)
# ─────────────────────────────────────────────
@router.get("/verify-email", response_class=HTMLResponse)
async def verify_email_page(token: str, db: AsyncSession = Depends(get_db)):
    ok = await confirm_email(db, token)
    return HTMLResponse(_notice_html(
        "Email verified" if ok else "Verification failed",
        "Your email address has been confirmed. You can now sign in." if ok
        else "This link is invalid or has expired.",
        ok,
    ))


# ─────────────────────────────────────────────
#  Forgot / reset password (web)
# ─────────────────────────────────────────────
@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_page(request: Request, sent: Optional[str] = None):
    return HTMLResponse(_forgot_html(sent=sent))


@router.post("/forgot-password", response_class=HTMLResponse)
async def forgot_submit(request: Request, email: str = Form(...),
                        db: AsyncSession = Depends(get_db)):
    user = await issue_password_reset(db, email)
    if user:
        try:
            await send_password_reset_email(user.email, user.reset_token)
        except Exception:
            pass
    return HTMLResponse(_forgot_html(sent="1"))


@router.get("/reset-password", response_class=HTMLResponse)
async def reset_page(request: Request, token: str = ""):
    return HTMLResponse(_reset_html(token=token))


@router.post("/reset-password", response_class=HTMLResponse)
async def reset_submit(request: Request, token: str = Form(...),
                       password: str = Form(...),
                       db: AsyncSession = Depends(get_db)):
    if len(password) < 8:
        return HTMLResponse(_reset_html(token=token, error="Password must be at least 8 characters."), status_code=400)
    ok = await confirm_password_reset(db, token, password)
    if not ok:
        return HTMLResponse(_reset_html(token=token, error="Invalid or expired reset link."), status_code=400)
    return HTMLResponse(_notice_html("Password updated", "You can now sign in with your new password.", True))


# ─── Inline HTML helpers (avoid extra template files) ───
def _twofa_html(error: Optional[str] = None) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8">
<title>Admin login code</title>
<style>body{{font-family:Arial,sans-serif;background:#f3f4f6;display:flex;height:100vh;align-items:center;justify-content:center}}
.card{{background:#fff;padding:28px 32px;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08);width:340px}}
input{{width:100%;padding:10px;margin:8px 0;box-sizing:border-box}}
button{{width:100%;padding:10px;background:#1d4ed8;color:#fff;border:0;border-radius:8px;cursor:pointer}}
.err{{color:#b91c1c;font-size:14px}}</style></head>
<body><div class="card"><h2>Admin login code</h2>
<p>Enter the 6-digit code we emailed you.</p>
{"<p class='err'>"+error+"</p>" if error else ""}
<form method="post"><input name="code" inputmode="numeric" autocomplete="one-time-code" placeholder="123456" required>
<button type="submit">Verify</button></form></div></body></html>"""


def _notice_html(title: str, body: str, ok: bool) -> str:
    color = "#047857" if ok else "#b91c1c"
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>{title}</title>
<style>body{{font-family:Arial,sans-serif;background:#f3f4f6;display:flex;height:100vh;align-items:center;justify-content:center}}
.card{{background:#fff;padding:28px 32px;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08);width:380px;text-align:center}}
h2{{color:{color}}}</style></head>
<body><div class="card"><h2>{title}</h2><p>{body}</p>
<p><a href="/auth/login">Back to sign in</a></p></div></body></html>"""


def _forgot_html(sent: Optional[str] = None) -> str:
    msg = "<p>We've sent a reset link if that email exists.</p>" if sent else ""
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Reset password</title>
<style>body{{font-family:Arial,sans-serif;background:#f3f4f6;display:flex;height:100vh;align-items:center;justify-content:center}}
.card{{background:#fff;padding:28px 32px;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08);width:340px}}
input{{width:100%;padding:10px;margin:8px 0;box-sizing:border-box}}
button{{width:100%;padding:10px;background:#1d4ed8;color:#fff;border:0;border-radius:8px;cursor:pointer}}</style></head>
<body><div class="card"><h2>Forgot password</h2>{msg}
<form method="post"><input type="email" name="email" placeholder="you@example.com" required>
<button type="submit">Send reset link</button></form>
<p><a href="/auth/login">Back to sign in</a></p></div></body></html>"""


def _reset_html(token: str = "", error: Optional[str] = None) -> str:
    return f"""<!doctype html><html><head><meta charset="utf-8"><title>Set new password</title>
<style>body{{font-family:Arial,sans-serif;background:#f3f4f6;display:flex;height:100vh;align-items:center;justify-content:center}}
.card{{background:#fff;padding:28px 32px;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08);width:340px}}
input{{width:100%;padding:10px;margin:8px 0;box-sizing:border-box}}
button{{width:100%;padding:10px;background:#1d4ed8;color:#fff;border:0;border-radius:8px;cursor:pointer}}
.err{{color:#b91c1c;font-size:14px}}</style></head>
<body><div class="card"><h2>Set a new password</h2>
{"<p class='err'>"+error+"</p>" if error else ""}
<form method="post"><input type="hidden" name="token" value="{token}">
<input type="password" name="password" placeholder="New password (8+ chars)" required>
<button type="submit">Update password</button></form></div></body></html>"""


# ─── Helpers ────────────────────────────────
def _post_auth_redirect_url(user: User, next_url: str, contractor_id: Optional[str] = None) -> str:
    if user.role == "customer":
        resolved_contractor_id = contractor_id if contractor_id and contractor_id.isdigit() else _contractor_id_from_next(next_url)
        if resolved_contractor_id:
            return f"/api/v1/jobs/auto-book?contractor_id={resolved_contractor_id}"
    # Only allow same-origin, single-slash paths. Reject protocol-relative
    # redirects like "//evil.com" which also satisfy startswith("/").
    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return _dashboard_url(user)


def _contractor_id_from_next(next_url: str) -> Optional[str]:
    parsed = urlparse(next_url or "")
    query = parse_qs(parsed.query)
    contractor_id = query.get("contractor_id", [None])[0]
    if contractor_id and contractor_id.isdigit():
        return contractor_id
    return None


def _dashboard_url(user: User) -> str:
    if user.role == "contractor":
        return "/dashboard/contractor"
    elif user.role == "admin":
        return "/admin"
    return "/dashboard/customer"
