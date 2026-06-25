from fastapi import APIRouter, Request, Depends, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

from app.api.dependencies import get_db, get_current_user_optional
from app.core.security import verify_password, create_access_token, get_password_hash
from app.models.all_models import User

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

    token = create_access_token(subject=user.id)
    redirect_url = _post_auth_redirect_url(user, next, contractor_id)
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
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
    db.add(user)
    await db.commit()
    await db.refresh(user)

    token = create_access_token(subject=user.id)
    redirect_url = _post_auth_redirect_url(user, next, contractor_id)
    response = RedirectResponse(url=redirect_url, status_code=302)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
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
        max_age=60 * 60 * 24 * 7,
    )
    return response


# ─────────────────────────────────────────────
#  GET  /auth/logout — clears cookie
# ─────────────────────────────────────────────
@router.get("/logout")
async def logout():
    response = RedirectResponse(url="/", status_code=302)
    response.delete_cookie("access_token")
    return response


# ─── Helpers ────────────────────────────────
def _post_auth_redirect_url(user: User, next_url: str, contractor_id: Optional[str] = None) -> str:
    if user.role == "customer":
        resolved_contractor_id = contractor_id if contractor_id and contractor_id.isdigit() else _contractor_id_from_next(next_url)
        if resolved_contractor_id:
            return f"/api/v1/jobs/auto-book?contractor_id={resolved_contractor_id}"
    return next_url if next_url.startswith("/") else _dashboard_url(user)


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
