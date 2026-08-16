import asyncio

from fastapi import APIRouter, Request, Depends, HTTPException, Form, status, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from sqlalchemy.orm import selectinload
from typing import Optional
from datetime import datetime, timedelta
from decimal import Decimal

from app.api.dependencies import get_current_user_optional, get_current_user, get_db
from app.models.all_models import User, Job, Conversation, DirectMessage, OmnichannelIntegration, Review, Escrow, Dispute, AIDraft, VerificationRequest, WalletTransaction, Receipt, MaterialOrder
from app.core.config import settings
from app.services import subscription_service
from app.services import wallet_service, upload_service
from app.services.escrow_service import calculate_fees, fund_escrow, release_escrow
from app.services.subscription_service import commission_rate
from app.core.security import verify_password, get_password_hash
from app.services.voice_dispatch import DISPATCH_STATE
from app.services.supplier_service import recommend_materials_for_job
from pathlib import Path

try:
    from app.models.audit_log import AIOperationsAuditLog
except ImportError:
    AIOperationsAuditLog = None

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["is_premium"] = subscription_service.is_premium

# Global money helpers so templates NEVER hardcode a currency symbol.
# ``escrow.currency`` is authoritative; fall back to the active charge currency.
def _symbol_for(currency: Optional[str]) -> str:
    code = (currency or "").upper() or \
        (settings.PAYSTACK_CURRENCY if settings.active_processor() == "paystack" else settings.PAYMENT_CURRENCY)
    return CURRENCY_SYMBOLS.get(code, "$")


# Public alias so both templates (registered as a Jinja global below) and Python
# callers (e.g. search_page / contractor pages building charge_symbol) can use it.
currency_symbol_for = _symbol_for

def fmt_money(amount, currency: Optional[str] = None) -> str:
    """Render an amount in the correct currency symbol (e.g. ₦1,200.00)."""
    try:
        val = float(amount or 0)
    except (TypeError, ValueError):
        val = 0.0
    return f"{_symbol_for(currency)}{val:,.2f}"

templates.env.globals["currency_symbol_for"] = _symbol_for
templates.env.globals["fmt_money"] = fmt_money


def voice_offer_out(o) -> dict:
    return {
        "contractor_id": o.contractor_id,
        "call_id": o.call_id,
        "raw_transcript": o.raw_transcript,
        "error": o.error,
        "result": o.result.model_dump(),
    }


router = APIRouter()

# ─────────────────────────────────────────────────────────────────────────────
# CURRENCY HELPERS (must be module-level so all route handlers can use them)
# ─────────────────────────────────────────────────────────────────────────────

# Currency mapping by country (display default only; actual charge currency is settings.PAYMENT_CURRENCY).
COUNTRY_CURRENCY_MAP = {
    "Nigeria": "NGN", "NG": "NGN",
    "United Kingdom": "GBP", "UK": "GBP", "GB": "GBP",
    "Kenya": "KES", "KE": "KES",
    "Ghana": "GHS", "GH": "GHS",
    "United States": "USD", "US": "USD",
    "Canada": "CAD", "CA": "CAD",
    "South Africa": "ZAR", "ZA": "ZAR",
    "India": "INR", "IN": "INR",
    "Australia": "AUD", "AU": "AUD",
    "United Arab Emirates": "AED", "AE": "AED",
    "Germany": "EUR", "DE": "EUR", "France": "EUR", "FR": "EUR",
    "Spain": "EUR", "ES": "EUR", "Italy": "EUR", "IT": "EUR",
    "Netherlands": "EUR", "NL": "EUR",
    "Tanzania": "TZS", "TZ": "TZS",
    "Uganda": "UGX", "UG": "UGX",
    "Ireland": "EUR", "IE": "EUR",
    "Singapore": "SGD", "SG": "SGD",
}

# Symbols for presentation.
CURRENCY_SYMBOLS = {
    "USD": "$", "NGN": "₦", "GBP": "£", "KES": "KSh ", "GHS": "GH₵",
    "CAD": "CA$", "EUR": "€", "ZAR": "R", "INR": "₹", "AUD": "A$",
    "AED": "د.إ", "TZS": "TSh", "UGX": "USh", "SGD": "S$",
}


def _detect_currency(user: User) -> str:
    """Detect display currency from user's country field."""
    country = getattr(user, 'country', None) or ''
    return COUNTRY_CURRENCY_MAP.get(country, 'USD')



def _flash_from_query(request: Request) -> Optional[dict]:
    """Map ?paid=1 / ?cancelled=1 / ?error=... query params to a dashboard flash message."""
    params = request.query_params
    if params.get("paid"):
        return {"kind": "success", "message": "Payment secured! Funds are held in escrow until you confirm the job is done."}
    if params.get("cancelled"):
        return {"kind": "success", "message": "Job cancelled. Any held payment has been refunded."}
    if params.get("success"):
        return {"kind": "success", "message": params["success"]}
    if params.get("error"):
        return {"kind": "error", "message": params["error"].replace("_", " ").capitalize()}
    return None

def format_location(obj) -> str:
    if not obj:
        return "—"
    parts = [part for part in [getattr(obj, 'area', None), getattr(obj, 'city', None), getattr(obj, 'state_or_province', None), getattr(obj, 'country', None)] if part]
    if parts:
        return ", ".join(parts)
    return getattr(obj, 'zip_code', None) or getattr(obj, 'postal_code', None) or "—"

@router.get("/about", response_class=HTMLResponse)
async def about_page(request: Request, current_user: Optional[User] = Depends(get_current_user_optional)):
    return templates.TemplateResponse(request=request, name="legal_page.html", context={
        "request": request,
        "current_user": current_user,
        "page_title": "About ServiceSync",
        "page_slug": "about",
    })


@router.get("/privacy", response_class=HTMLResponse)
async def privacy_page(request: Request, current_user: Optional[User] = Depends(get_current_user_optional)):
    return templates.TemplateResponse(request=request, name="legal_page.html", context={
        "request": request,
        "current_user": current_user,
        "page_title": "Privacy Policy",
        "page_slug": "privacy",
    })


@router.get("/terms", response_class=HTMLResponse)
async def terms_page(request: Request, current_user: Optional[User] = Depends(get_current_user_optional)):
    return templates.TemplateResponse(request=request, name="legal_page.html", context={
        "request": request,
        "current_user": current_user,
        "page_title": "Terms of Service",
        "page_slug": "terms",
    })


@router.get("/", response_class=HTMLResponse)
async def homepage(request: Request, current_user: Optional[User] = Depends(get_current_user_optional)):
    # Redirect if logged in
    if current_user:
        if current_user.role == "customer":
            return RedirectResponse(url="/dashboard/customer")
        elif current_user.role == "contractor":
            return RedirectResponse(url="/dashboard/contractor")
        elif current_user.role == "admin":
            return RedirectResponse(url="/admin")
    return templates.TemplateResponse(request=request, name="index.html", context={"request": request, "current_user": current_user})

@router.get("/search", response_class=HTMLResponse)
async def search_page(request: Request, current_user: Optional[User] = Depends(get_current_user_optional)):
    return templates.TemplateResponse(request=request, name="search.html", context={
        "request": request,
        "current_user": current_user,
        "charge_currency": settings.PAYSTACK_CURRENCY if settings.active_processor() == "paystack" else settings.PAYMENT_CURRENCY,
        "charge_symbol": currency_symbol_for(settings.PAYSTACK_CURRENCY if settings.active_processor() == "paystack" else settings.PAYMENT_CURRENCY),
    })


@router.get("/tools", response_class=HTMLResponse)
async def tools_index_page(
    request: Request, current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Phase 5 — free-tools funnel landing (public, ad-supported)."""
    return templates.TemplateResponse(request=request, name="tools_index.html", context={
        "request": request,
        "current_user": current_user,
    })


@router.get("/tools/cctv-calculator", response_class=HTMLResponse)
async def cctv_calculator_page(
    request: Request, current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Public CCTV estimator that funnels into the CCTV marketplace."""
    return templates.TemplateResponse(request=request, name="cctv_calculator.html", context={
        "request": request,
        "current_user": current_user,
    })


@router.get("/tools/solar-calculator", response_class=HTMLResponse)
async def solar_calculator_page(
    request: Request, current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Public solar estimator that funnels into the marketplace."""
    return templates.TemplateResponse(request=request, name="solar_calculator.html", context={
        "request": request,
        "current_user": current_user,
    })


@router.get("/tools/quote-calculator", response_class=HTMLResponse)
async def quote_calculator_page(
    request: Request, current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Public service-quote estimator that funnels into the marketplace."""
    return templates.TemplateResponse(request=request, name="quote_calculator.html", context={
        "request": request,
        "current_user": current_user,
    })


@router.get("/tools/bom-calculator", response_class=HTMLResponse)
async def bom_calculator_page(
    request: Request, current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Public project / bill-of-materials calculator that funnels into the marketplace."""
    return templates.TemplateResponse(request=request, name="bom_calculator.html", context={
        "request": request,
        "current_user": current_user,
    })


@router.get("/tools/price-estimator", response_class=HTMLResponse)
async def price_estimator_page(
    request: Request, current_user: Optional[User] = Depends(get_current_user_optional)
):
    """Public market service-price range estimator that funnels into the marketplace."""
    return templates.TemplateResponse(request=request, name="price_estimator.html", context={
        "request": request,
        "current_user": current_user,
    })


@router.get("/tools/request-pro")
async def request_pro(
    request: Request, trade: str = "general", redirect: str = "/contractors",
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    """Phase 6 — convert a free-tool estimate into a real Job lead.

    Authenticated customers get a Job (status=open) pre-filled from the estimate so
    it drops straight into the marketplace (contractors can quote it). Guests are
    sent to sign-up first. This is the funnel -> transaction bridge.
    """
    from urllib.parse import quote

    if not redirect.startswith("/"):
        redirect = "/contractors"

    if not current_user or current_user.role != "customer":
        target = f"/tools/request-pro?trade={quote(trade)}&redirect={quote(redirect)}"
        return RedirectResponse(url=f"/auth/signup?next={quote(target)}")

    job = Job(
        customer_id=current_user.id,
        category=trade.lower(),
        status="open",
        description=f"Estimate request — {trade.title()}",
        brief={"source": "free_tool", "trade": trade.lower()},
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    # Phase 6: route the lead to matched contractors (records match + emails them).
    try:
        from app.services.lead_service import notify_matched_contractors_for_lead
        await notify_matched_contractors_for_lead(db, job)
        await db.commit()
    except Exception:
        await db.rollback()
    return RedirectResponse(url=redirect)


@router.get("/leads", response_class=HTMLResponse)
async def leads_page(
    request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Contractor lead board — open jobs in the contractor's trade."""
    if current_user.role != "contractor":
        raise HTTPException(status_code=403, detail="Contractor only")
    from app.services.lead_service import open_leads_for_contractor

    leads = await open_leads_for_contractor(db, current_user)
    lead_data = []
    for job in leads:
        conv = (await db.exec(select(Conversation).where(Conversation.job_id == job.id))).first()
        lead_data.append({"job": job, "conversation_id": conv.id if conv else None})
    return templates.TemplateResponse(request=request, name="leads.html", context={
        "request": request,
        "current_user": current_user,
        "leads": lead_data,
    })


@router.get("/materials", response_class=HTMLResponse)
async def materials_board_page(
    request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)
):
    """Contractor/Admin materials board — recommended BOM + procurement status."""
    if current_user.role not in ("contractor", "admin"):
        raise HTTPException(status_code=403, detail="Contractor/Admin only")
    if current_user.role == "admin":
        result = await db.exec(select(Job).limit(200))
    else:
        result = await db.exec(select(Job).where(Job.assigned_contractor_id == current_user.id))
    boards = []
    for job in result.all():
        order = await db.exec(select(MaterialOrder).where(MaterialOrder.job_id == job.id))
        order = order.first()
        boards.append({
            "job": job,
            "materials": recommend_materials_for_job(job),
            "order": order,
        })
    return templates.TemplateResponse(request=request, name="materials.html", context={
        "request": request,
        "current_user": current_user,
        "boards": boards,
    })


@router.get("/contractors", response_class=HTMLResponse)
async def contractor_listing(
    request: Request,
    profession: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    sort: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    query = select(User).where(User.role == "contractor")
    if profession:
        query = query.where(User.profession.ilike(f"%{profession}%"))
    if city:
        query = query.where(User.city.ilike(f"%{city}%"))
    if country:
        query = query.where(User.country.ilike(f"%{country}%"))
    result = await db.exec(query)
    contractors = list(result.all())

    # Server-side sort
    if sort == "price_asc":
        contractors.sort(key=lambda c: float(c.base_pricing or 0))
    elif sort == "price_desc":
        contractors.sort(key=lambda c: float(c.base_pricing or 0), reverse=True)
    elif sort == "rating":
        contractors.sort(key=lambda c: float(c.reputation_score or 0), reverse=True)
    else:
        # Default: boosted first, then by reputation
        from datetime import datetime as _dt
        now = _dt.utcnow()
        contractors.sort(
            key=lambda c: (
                0 if (c.boosted_until and c.boosted_until > now) else 1,
                -float(c.reputation_score or 0),
            )
        )

    return templates.TemplateResponse(request=request, name="contractor_listing.html", context={
        "request": request,
        "current_user": current_user,
        "contractors": contractors,
        "format_location": format_location,
        "filters": {"profession": profession, "city": city, "country": country},
        "sort": sort or "",
        "charge_currency": settings.PAYSTACK_CURRENCY if settings.active_processor() == "paystack" else settings.PAYMENT_CURRENCY,
    })


@router.get("/contractors/{contractor_id}", response_class=HTMLResponse)
async def contractor_public_profile(
    request: Request,
    contractor_id: int,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    contractor = await db.get(User, contractor_id)
    if not contractor or contractor.role != "contractor":
        raise HTTPException(status_code=404, detail="Contractor not found")

    reviews_result = await db.exec(
        select(Review).where(Review.contractor_id == contractor_id).order_by(Review.created_at.desc())
    )
    reviews = reviews_result.all()

    completed_jobs_result = await db.exec(
        select(Job).where(Job.assigned_contractor_id == contractor_id, Job.status == "completed")
    )
    completed_jobs_count = len(completed_jobs_result.all())

    return templates.TemplateResponse(request=request, name="contractor_profile.html", context={
        "request": request,
        "current_user": current_user,
        "contractor": contractor,
        "reviews": reviews,
        "completed_jobs_count": completed_jobs_count,
        "charge_currency": settings.PAYSTACK_CURRENCY if settings.active_processor() == "paystack" else settings.PAYMENT_CURRENCY,
        "format_location": format_location,
    })

@router.get("/integrations", response_class=HTMLResponse)
async def integrations_page(request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "contractor":
        return RedirectResponse(url="/")
        
    result = await db.exec(select(OmnichannelIntegration).where(OmnichannelIntegration.contractor_id == current_user.id))
    integrations = result.all()
    
    return templates.TemplateResponse(request=request, name="integrations.html", context={
        "request": request,
        "current_user": current_user,
        "integrations": integrations,
        "charge_currency": settings.PAYSTACK_CURRENCY if settings.active_processor() == "paystack" else settings.PAYMENT_CURRENCY,
        "charge_symbol": currency_symbol_for(settings.PAYSTACK_CURRENCY if settings.active_processor() == "paystack" else settings.PAYMENT_CURRENCY),
    })


@router.post("/integrations/save-ai-settings")
async def save_ai_settings(
    request: Request,
    ai_tone_preference: str = Form(default="professional"),
    base_pricing: float = Form(default=0.0),
    service_radius_miles: int = Form(default=25),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "contractor":
        return RedirectResponse(url="/")

    current_user.ai_tone_preference = ai_tone_preference
    current_user.base_pricing = base_pricing
    current_user.service_radius_miles = service_radius_miles
    db.add(current_user)
    await db.commit()
    return RedirectResponse(url="/integrations?saved=ai", status_code=302)


@router.post("/integrations/save-constraints")
async def save_constraints(
    request: Request,
    working_hours_start: str = Form(default="08:00"),
    working_hours_end: str = Form(default="18:00"),
    max_daily_jobs: int = Form(default=4),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "contractor":
        return RedirectResponse(url="/")

    current_user.working_hours_start = working_hours_start
    current_user.working_hours_end = working_hours_end
    current_user.max_daily_jobs = max_daily_jobs
    db.add(current_user)
    await db.commit()
    return RedirectResponse(url="/integrations?saved=constraints", status_code=302)


@router.post("/integrations/save-autonomy")
async def save_autonomy(
    request: Request,
    ai_autonomy_level: int = Form(default=1),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "contractor":
        return RedirectResponse(url="/")

    if ai_autonomy_level not in (1, 2, 3):
        ai_autonomy_level = 1
    current_user.ai_autonomy_level = ai_autonomy_level
    db.add(current_user)
    await db.commit()
    return RedirectResponse(url="/integrations?saved=autonomy", status_code=302)


@router.post("/verification/submit")
async def submit_verification(
    requested_level: str = Form(...),
    id_document: Optional[UploadFile] = File(None),
    license_document: Optional[UploadFile] = File(None),
    insurance_document: Optional[UploadFile] = File(None),
    notes: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Contractor submits documents to request a verification tier."""
    if current_user.role != "contractor":
        return RedirectResponse(url="/")

    valid_levels = {"Bronze", "Silver", "Gold", "Verified Pro"}
    if requested_level not in valid_levels:
        requested_level = "Bronze"

    # If there is already a pending request, don't create a duplicate
    existing = await db.exec(
        select(VerificationRequest).where(
            VerificationRequest.contractor_id == current_user.id,
            VerificationRequest.status == "pending",
        )
    )
    if existing.first():
        return RedirectResponse(url="/dashboard/contractor?verify=pending", status_code=302)

    from urllib.parse import quote
    doc_allowlist = upload_service._IMAGE_EXT | upload_service._DOC_EXT
    id_url = license_url = insurance_url = None

    try:
        if id_document and id_document.filename:
            data = await id_document.read()
            if data:
                id_url = await upload_service.save_upload(
                    data, id_document.filename,
                    allowlist=doc_allowlist, max_bytes=10*1024*1024, folder="verifications"
                )

        if license_document and license_document.filename:
            data = await license_document.read()
            if data:
                license_url = await upload_service.save_upload(
                    data, license_document.filename,
                    allowlist=doc_allowlist, max_bytes=10*1024*1024, folder="verifications"
                )

        if insurance_document and insurance_document.filename:
            data = await insurance_document.read()
            if data:
                insurance_url = await upload_service.save_upload(
                    data, insurance_document.filename,
                    allowlist=doc_allowlist, max_bytes=10*1024*1024, folder="verifications"
                )
    except ValueError as e:
        return RedirectResponse(url=f"/dashboard/contractor?error={quote(str(e))}", status_code=302)

    req = VerificationRequest(
        contractor_id=current_user.id,
        requested_level=requested_level,
        id_document_url=id_url,
        license_document_url=license_url,
        insurance_document_url=insurance_url,
        notes=notes.strip() or None,
        status="pending",
    )
    db.add(req)
    await db.commit()
    return RedirectResponse(url="/dashboard/contractor?verify=submitted", status_code=302)


@router.get("/billing", response_class=HTMLResponse)
async def billing_page(request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Contractor subscription / billing page (Free vs Premium)."""
    if current_user.role != "contractor":
        return RedirectResponse(url="/")

    # Self-heal expired trials/subscriptions on load
    current_user = await subscription_service.enforce_expiry(db, current_user)

    tier = subscription_service.effective_tier(current_user)
    ctx = {
        "request": request,
        "current_user": current_user,
        "effective_tier": tier,
        "is_premium": tier == "premium",
        "is_trialing": subscription_service.is_trial_active(current_user),
        "trial_days_remaining": subscription_service.trial_days_remaining(current_user),
        "commission_rate": float(subscription_service.commission_rate(current_user)) * 100,
        "free_fee_pct": settings.PLATFORM_FEE_PCT_FREE * 100,
        "premium_fee_pct": settings.PLATFORM_FEE_PCT_PREMIUM * 100,
        "premium_price": settings.PREMIUM_MONTHLY_PRICE,
        "trial_days": settings.PREMIUM_TRIAL_DAYS,
        "wallet_balance": float((await wallet_service.get_wallet(db, current_user.id)).available_balance),
        "charge_currency": settings.PAYSTACK_CURRENCY if settings.active_processor() == "paystack" else settings.PAYMENT_CURRENCY,
    }
    return templates.TemplateResponse(request=request, name="billing.html", context=ctx)


@router.post("/billing/upgrade")
async def billing_upgrade(
    payment_method: str = Form(default="card"),
    card_number: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Upgrade to Premium. Payment can be taken by card or from cleared wallet earnings."""
    if current_user.role != "contractor":
        return RedirectResponse(url="/")

    price = Decimal(str(settings.PREMIUM_MONTHLY_PRICE))

    if payment_method == "wallet":
        from app.services import wallet_service
        try:
            await wallet_service.pay_subscription_from_wallet(
                db, current_user.id, price,
                reference=f"sub_wallet_{current_user.id}_{int(datetime.utcnow().timestamp())}",
                note="Premium subscription (paid from earnings)",
            )
        except ValueError as e:
            return RedirectResponse(url=f"/billing?error={e}", status_code=302)
    else:
        # Mock card capture (Stripe when STRIPE_SECRET_KEY is set)
        from app.services.payment_gateway import capture_payment
        digits = "".join(ch for ch in card_number if ch.isdigit())
        card_brand = "Visa" if digits.startswith("4") else "Mastercard" if digits.startswith("5") else "Card"
        card_last4 = digits[-4:] if len(digits) >= 12 else "0000"
        capture_payment(price, "usd", card_brand, card_last4,
                        metadata={"kind": "subscription", "contractor_id": str(current_user.id)})

    subscription_service.upgrade_to_premium(current_user)
    db.add(current_user)
    await db.commit()
    return RedirectResponse(url="/billing?upgraded=1", status_code=302)


@router.post("/billing/cancel")
async def billing_cancel(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "contractor":
        return RedirectResponse(url="/")
    subscription_service.cancel_subscription(current_user)
    db.add(current_user)
    await db.commit()
    return RedirectResponse(url="/billing?cancelled=1", status_code=302)


@router.post("/contractor/boost")
async def contractor_boost(current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Spend cleared wallet earnings to boost profile to the top of search for 24h."""
    if current_user.role != "contractor":
        return RedirectResponse(url="/")
    price = Decimal(str(settings.BOOST_PRICE))
    try:
        await wallet_service.pay_subscription_from_wallet(
            db, current_user.id, price,
            reference=f"boost_{current_user.id}_{int(datetime.utcnow().timestamp())}",
            note="24h search boost",
        )
    except ValueError as e:
        return RedirectResponse(url=f"/dashboard/contractor?error={e}", status_code=302)
    current_user.boosted_until = datetime.utcnow() + timedelta(hours=24)
    db.add(current_user)
    await db.commit()
    return RedirectResponse(url="/dashboard/contractor?boosted=1", status_code=302)


@router.get("/analytics", response_class=HTMLResponse)
async def analytics_page(request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Premium-only advanced analytics dashboard for contractors."""
    if current_user.role != "contractor":
        return RedirectResponse(url="/")

    current_user = await subscription_service.enforce_expiry(db, current_user)
    premium = subscription_service.is_premium(current_user)

    metrics = None
    earnings_released = 0.0
    earnings_pending = 0.0
    active_jobs = 0
    if premium:
        from app.services.reputation_service import compute_reputation_metrics
        metrics = await compute_reputation_metrics(db, current_user.id)

        # Earnings from escrows
        escrows_result = await db.exec(select(Escrow).where(Escrow.contractor_id == current_user.id))
        for e in escrows_result.all():
            if e.status == "released":
                earnings_released += float(e.contractor_payout)
            elif e.status == "held":
                earnings_pending += float(e.contractor_payout)

        jobs_result = await db.exec(
            select(Job).where(Job.assigned_contractor_id == current_user.id, Job.status == "booked")
        )
        active_jobs = len(jobs_result.all())

    return templates.TemplateResponse(request=request, name="analytics.html", context={
        "request": request,
        "current_user": current_user,
        "is_premium": premium,
        "metrics": metrics,
        "earnings_released": earnings_released,
        "earnings_pending": earnings_pending,
        "active_jobs": active_jobs,
        "charge_currency": settings.PAYSTACK_CURRENCY if settings.active_processor() == "paystack" else settings.PAYMENT_CURRENCY,
    })


@router.get("/wallet", response_class=HTMLResponse)
async def wallet_page(request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Contractor earnings wallet: pending (clearing) + available balances + history."""
    if current_user.role != "contractor":
        return RedirectResponse(url="/")

    current_user = await subscription_service.enforce_expiry(db, current_user)
    wallet = await wallet_service.get_wallet(db, current_user.id)

    txns_result = await db.exec(
        select(WalletTransaction)
        .where(WalletTransaction.contractor_id == current_user.id)
        .order_by(WalletTransaction.created_at.desc())
    )
    txns = txns_result.all()

    clearing_days = settings.PREMIUM_CLEARING_DAYS if subscription_service.is_premium(current_user) else settings.CLEARING_DAYS
    wallet_currency = (wallet.currency or settings.PAYMENT_CURRENCY).upper()
    return templates.TemplateResponse(request=request, name="wallet.html", context={
        "request": request,
        "current_user": current_user,
        "is_premium": subscription_service.is_premium(current_user),
        "wallet": wallet,
        "transactions": txns,
        "clearing_days": clearing_days,
        "wallet_currency": wallet_currency,
        "wallet_symbol": CURRENCY_SYMBOLS.get(wallet_currency, "$"),
        "payout_method_set": bool(current_user.paystack_recipient_code or current_user.stripe_account_id),
    })


@router.post("/wallet/withdraw")
async def wallet_withdraw(
    amount: float = Form(...),
    method: str = Form(default="bank"),
    bank_account: str = Form(default=""),
    mobile_provider: str = Form(default=""),
    phone: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "contractor":
        return RedirectResponse(url="/")
    dest = "linked account"
    if method == "mobile":
        dest = f"{(mobile_provider or 'mobile').title()} {phone[-4:] if phone and len(phone) >= 4 else phone or ''}".strip()
    elif bank_account:
        last4 = "".join(ch for ch in bank_account if ch.isdigit())[-4:]
        dest = f"bank ····{last4}" if last4 else "bank account"
    try:
        wallet = await wallet_service.get_wallet(db, current_user.id)
        txn = await wallet_service.withdraw(
            db, current_user.id, Decimal(str(amount)),
            currency=wallet.currency,
            reference=f"wd_{current_user.id}_{int(datetime.utcnow().timestamp())}",
            note=f"Withdrawal via {method} to {dest}",
            method=method,
        )
    except ValueError as e:
        return RedirectResponse(url=f"/wallet?error={e}", status_code=302)
    return RedirectResponse(url="/wallet?withdrawn=1", status_code=302)


@router.get("/jobs/{job_id}/pay", response_class=HTMLResponse)
async def pay_job_page(request: Request, job_id: int, error: Optional[str] = None, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Customer payment screen: review quote, platform fee, contractor payout, pay & secure escrow."""
    if current_user.role != "customer":
        return RedirectResponse(url="/")

    job = await db.get(Job, job_id)
    if not job or job.customer_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    contractor = await db.get(User, job.assigned_contractor_id) if job.assigned_contractor_id else None
    result = await db.exec(select(Escrow).where(Escrow.job_id == job_id))
    escrow = result.first()

    # Determine the USD quote (quote if present, else contractor base pricing)
    usd_amount = float((escrow.quoted_amount if escrow and escrow.quoted_amount else Decimal(str(contractor.base_pricing or 50.00))) if (escrow or contractor) else Decimal("50.00"))
    if escrow and escrow.status == "held":
        # Already funded
        return RedirectResponse(url=f"/dashboard/customer", status_code=302)

    # Pick the active processor and derive the charge amount/currency to display.
    processor = settings.active_processor()
    # Both processors can be configured; only the "active" one is used for
    # charging, but the template passes both flags for UI flexibility.
    is_paystack = processor == "paystack"
    if is_paystack:
        charge_currency = settings.PAYSTACK_CURRENCY
        charge_symbol = CURRENCY_SYMBOLS.get(charge_currency, "₦")
        charge_amount = round(usd_amount * settings.USD_NGN_RATE, 2)
    else:
        charge_currency = settings.PAYMENT_CURRENCY
        charge_symbol = CURRENCY_SYMBOLS.get(charge_currency, "$")
        charge_amount = usd_amount
    charge_kobo = int(round(charge_amount * 100))

    fees = calculate_fees(Decimal(str(charge_amount)), rate=commission_rate(contractor))
    from app.models.all_models import PaymentMethod
    pm_result = await db.exec(
        select(PaymentMethod)
        .where(PaymentMethod.user_id == current_user.id)
        .order_by(PaymentMethod.is_default.desc(), PaymentMethod.id.desc())
    )
    saved_methods = pm_result.all()
    return templates.TemplateResponse(request=request, name="pay_job.html", context={
        "request": request,
        "current_user": current_user,
        "job": job,
        "contractor": contractor,
        "amount": float(charge_amount),
        "platform_fee": float(fees["platform_fee"]),
        "contractor_payout": float(fees["contractor_payout"]),
        "is_funded": escrow is not None and escrow.status == "held",
        "error": error,
        "format_location": format_location,
        "currency": charge_currency,
        "charge_currency": charge_currency,
        "currency_symbol": charge_symbol,
        "charge_kobo": charge_kobo,
        "min_amount": settings.MIN_PAYMENT_AMOUNT,
        "saved_methods": saved_methods,
        "processor": processor,
        "paystack_live": settings.paystack_live,
        "paystack_pk": settings.PAYSTACK_PUBLIC_KEY or "",
        "paystack_email": current_user.email or "",
        "paystack_init_url": f"/jobs/{job_id}/paystack-init",
        "stripe_live": bool(settings.STRIPE_SECRET_KEY and settings.STRIPE_PUBLISHABLE_KEY),
        "stripe_pk": settings.STRIPE_PUBLISHABLE_KEY or "",
    })


@router.post("/jobs/{job_id}/create-intent")
async def create_job_payment_intent(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Create a Stripe PaymentIntent for the pay screen (live mode). Returns the
    client_secret for Stripe Elements. In mock mode client_secret is null and the
    frontend falls back to the demo form."""
    if current_user.role != "customer":
        raise HTTPException(status_code=403, detail="Not authorized")
    job = await db.get(Job, job_id)
    if not job or job.customer_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    contractor = await db.get(User, job.assigned_contractor_id) if job.assigned_contractor_id else None
    result = await db.exec(select(Escrow).where(Escrow.job_id == job_id))
    escrow = result.first()
    amount = (escrow.quoted_amount if escrow and escrow.quoted_amount
              else Decimal(str((contractor.base_pricing if contractor else None) or 50.00)))

    # Enforce the platform minimum before touching the gateway. Use the per-currency
    # floor so e.g. USD doesn't get clamped at the NGN level (or vice versa).
    from app.services.payment_gateway import charge_minimum
    charge_currency = settings.PAYMENT_CURRENCY
    if amount < charge_minimum(charge_currency):
        raise HTTPException(
            status_code=400,
            detail=f"Minimum charge is {settings.min_payment_for(charge_currency):g} {charge_currency}.",
        )
    # Run the blocking Stripe SDK call off the event loop, with a timeout so a slow
    # or hung gateway can't leave the client spinner running forever.
    from app.services import payment_gateway
    try:
        intent = await asyncio.wait_for(
            asyncio.to_thread(
                payment_gateway.create_payment_intent,
                Decimal(str(amount)), currency=settings.PAYMENT_CURRENCY.lower(),
                metadata={"job_id": str(job_id), "customer_id": str(current_user.id)},
            ),
            timeout=25,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Payment provider timed out. Please try again.")
    return {
        "client_secret": intent.get("client_secret"),
        "reference_id": intent.get("reference_id"),
        "mode": intent.get("mode"),
        "amount": float(amount),
        "currency": settings.PAYMENT_CURRENCY,
    }


@router.post("/jobs/{job_id}/paystack-init")
async def create_paystack_transaction_endpoint(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Initialize a Paystack transaction for the pay screen (live mode). Returns the
    reference + access_code the client uses to open the Paystack inline popup. The
    amount is derived server-side from the job quote (USD -> NGN) and never trusted
    from the client."""
    if not settings.paystack_live:
        raise HTTPException(status_code=400, detail="Paystack is not configured")
    if current_user.role != "customer":
        raise HTTPException(status_code=403, detail="Not authorized")
    job = await db.get(Job, job_id)
    if not job or job.customer_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    contractor = await db.get(User, job.assigned_contractor_id) if job.assigned_contractor_id else None
    result = await db.exec(select(Escrow).where(Escrow.job_id == job_id))
    escrow = result.first()
    usd_amount = float((escrow.quoted_amount if escrow and escrow.quoted_amount
                        else Decimal(str((contractor.base_pricing if contractor else None) or 50.00))))
    kobo = int(round(usd_amount * settings.USD_NGN_RATE * 100))
    # Paystack NGN floor is ₦100 (= 10,000 kobo). Enforce server-side via the
    # same per-currency helper used elsewhere so the error matches the rest of
    # the pay flow.
    from app.services.payment_gateway import charge_minimum
    min_ngn = float(charge_minimum(settings.PAYSTACK_CURRENCY))  # Decimal -> float
    if kobo < int(round(min_ngn * 100)):
        raise HTTPException(
            status_code=400,
            detail=f"Minimum charge is \u20a6{min_ngn:,.2f} {settings.PAYSTACK_CURRENCY}.",
        )

    from app.services import payment_gateway
    try:
        tx = await asyncio.wait_for(
            asyncio.to_thread(
                payment_gateway.create_paystack_transaction,
                kobo, current_user.email or "customer@example.com",
                {"job_id": str(job_id), "customer_id": str(current_user.id)},
                settings.PAYSTACK_CURRENCY,
            ),
            timeout=25,
        )
    except asyncio.TimeoutError:
        raise HTTPException(status_code=504, detail="Payment provider timed out. Please try again.")
    if not tx.get("success"):
        raise HTTPException(status_code=502, detail=f"Could not start payment: {tx.get('error', 'unknown error')}")
    return {
        "reference": tx.get("reference"),
        "access_code": tx.get("access_code"),
        "authorization_url": tx.get("authorization_url"),
        "mode": "paystack",
    }


@router.get("/jobs/{job_id}/receipt", response_class=HTMLResponse)
async def job_receipt_page(request: Request, job_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Customer payment receipt / invoice (also visible to the contractor)."""
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    if current_user.id not in (job.customer_id, job.assigned_contractor_id):
        return RedirectResponse(url="/")

    receipt_result = await db.exec(
        select(Receipt).where(Receipt.job_id == job_id).order_by(Receipt.issued_at.desc())
    )
    receipt = receipt_result.first()
    if not receipt:
        return RedirectResponse(url=f"/jobs/{job_id}/pay", status_code=302)

    contractor = await db.get(User, receipt.contractor_id)
    customer = await db.get(User, receipt.customer_id)

    # Escrow for timeline + status-aware header
    escrow_result = await db.exec(select(Escrow).where(Escrow.job_id == job_id))
    escrow = escrow_result.first()

    # Currency symbol from receipt or current processor
    currency_code = (receipt.currency or "USD").upper()
    currency_sym = CURRENCY_SYMBOLS.get(currency_code, "$")

    # Linked conversation for chat button
    from app.models.all_models import Conversation
    conv_result = await db.exec(
        select(Conversation).where(Conversation.job_id == job_id)
    )
    conv = conv_result.first()

    return templates.TemplateResponse(request=request, name="receipt.html", context={
        "request": request,
        "current_user": current_user,
        "receipt": receipt,
        "job": job,
        "contractor": contractor,
        "customer": customer,
        "escrow": escrow,
        "currency_symbol": currency_sym,
        "charge_currency": settings.PAYSTACK_CURRENCY if settings.active_processor() == "paystack" else settings.PAYMENT_CURRENCY,
        "conversation_id": conv.id if conv else None,
        "format_location": format_location,
    })


@router.post("/escrow/{job_id}/fund", response_class=HTMLResponse)
async def web_fund_escrow(
    job_id: int,
    quoted_amount: float = Form(...),
    payment_type: str = Form(default="card"),
    card_brand: str = Form(default=""),
    card_last4: str = Form(default=""),
    card_number: str = Form(default=""),
    bank_account_number: str = Form(default=""),
    mobile_provider: str = Form(default=""),
    mobile_phone: str = Form(default=""),
    saved_method_id: Optional[str] = Form(default=None),
    currency: str = Form(default="USD"),
    payment_intent_id: Optional[str] = Form(default=None),
    paystack_reference: Optional[str] = Form(default=None),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Customer pays & funds the escrow from the pay page; redirects to dashboard."""
    if current_user.role != "customer":
        return RedirectResponse(url="/")

    from urllib.parse import quote

    # In live mode (Stripe OR Paystack) every funded escrow must come from a real
    # gateway charge. Reject stale demo bank/mobile submissions that carry neither.
    live = bool(settings.STRIPE_SECRET_KEY or settings.PAYSTACK_SECRET_KEY)
    if live and not payment_intent_id and not paystack_reference:
        return RedirectResponse(
            url=f"/jobs/{job_id}/pay?error={quote('A real payment is required to fund this escrow.')}",
            status_code=302,
        )

    job = await db.get(Job, job_id)
    if not job or job.customer_id != current_user.id:
        return RedirectResponse(url="/dashboard/customer?error=job_not_found", status_code=302)
    if job.status != "booked":
        return RedirectResponse(url="/dashboard/customer?error=not_bookable", status_code=302)

    contractor = await db.get(User, job.assigned_contractor_id) if job.assigned_contractor_id else None
    if not contractor:
        return RedirectResponse(url="/dashboard/customer?error=no_contractor", status_code=302)

    # Process payment method
    final_brand = card_brand
    final_last4 = card_last4

    saved_id = None
    if saved_method_id and str(saved_method_id).strip().isdigit():
        saved_id = int(saved_method_id)

    if saved_id:
        from app.models.all_models import PaymentMethod
        method = await db.get(PaymentMethod, saved_id)
        if method and method.user_id == current_user.id:
            final_brand = method.brand or (method.provider.title() if method.provider else "Card")
            final_last4 = method.last4 or ""
            if method.type == "bank_transfer":
                final_brand = method.bank_name or "Bank Transfer"
            elif method.type == "mobile_money":
                final_brand = (method.provider or "Mobile").title()
    else:
        if payment_type == 'card':
            if not final_last4 and card_number:
                digits = "".join(ch for ch in card_number if ch.isdigit())
                final_last4 = digits[-4:] if len(digits) >= 4 else ""
                if digits.startswith("4"):
                    final_brand = "Visa"
                elif digits.startswith("5"):
                    final_brand = "Mastercard"
                else:
                    final_brand = "Card"
        elif payment_type == 'bank':
            final_brand = "Bank Transfer"
            final_last4 = bank_account_number[-4:] if len(bank_account_number) >= 4 else ""
        elif payment_type == 'mobile':
            final_brand = mobile_provider.title() if mobile_provider else "Mobile"
            digits = "".join(ch for ch in mobile_phone if ch.isdigit())
            final_last4 = digits[-4:] if len(digits) >= 4 else ""

    if not final_brand:
        final_brand = "Card"

    try:
        from app.services.escrow_service import fund_escrow
        # Paystack path: verify the transaction server-side before trusting it.
        if paystack_reference and settings.paystack_live:
            from app.services import payment_gateway as pgw
            v = await asyncio.wait_for(
                asyncio.to_thread(pgw.verify_paystack_transaction, paystack_reference),
                timeout=25,
            )
            if not v.get("success") or v.get("status") != "success":
                return RedirectResponse(
                    url=f"/jobs/{job_id}/pay?error={quote('Payment could not be verified with Paystack. Please try again.')}",
                    status_code=302,
                )
            verified_amount = float((v.get("amount") or 0)) / 100.0
            auth = v.get("authorization") or {}
            final_brand = auth.get("card_type") or "Paystack"
            final_last4 = auth.get("last4") or ""
            await fund_escrow(
                db, job, current_user, contractor,
                Decimal(str(verified_amount)), final_brand, final_last4,
                paystack_reference=paystack_reference,
            )
        else:
            await fund_escrow(
                db, job, current_user, contractor,
                Decimal(str(quoted_amount)), final_brand, final_last4,
                payment_gateway_id=payment_intent_id,
            )
    except ValueError as e:
        from urllib.parse import quote
        return RedirectResponse(url=f"/jobs/{job_id}/pay?error={quote(str(e))}", status_code=302)

    await db.commit()
    # Prefer chat thread so customer sees funded status + next job actions
    conv = (await db.exec(select(Conversation).where(Conversation.job_id == job_id))).first()
    if conv:
        return RedirectResponse(url=f"/chat/{conv.id}?paid=1", status_code=302)
    return RedirectResponse(url="/dashboard/customer?paid=1", status_code=302)


@router.post("/escrow/{job_id}/release", response_class=HTMLResponse)
async def web_release_escrow(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Customer confirms completion and releases the escrow from the dashboard.

    Mirrors the JSON API but returns an HTML redirect. Guarded by ownership and
    job-status so a job can only be released once confirmed complete.
    """
    if current_user.role != "customer":
        return RedirectResponse(url="/", status_code=302)

    job = await db.get(Job, job_id)
    if not job or job.customer_id != current_user.id:
        return RedirectResponse(url="/dashboard/customer?error=not_found", status_code=302)
    if job.status != "completed_pending":
        return RedirectResponse(url="/dashboard/customer?error=not_confirmable", status_code=302)

    result = await db.exec(select(Escrow).where(Escrow.job_id == job_id))
    escrow = result.first()
    if not escrow:
        return RedirectResponse(url="/dashboard/customer?error=no_escrow", status_code=302)
    if escrow.customer_id != current_user.id:
        return RedirectResponse(url="/dashboard/customer?error=not_yours", status_code=302)

    try:
        await release_escrow(db, escrow)
        job.status = "completed"
        db.add(job)
        try:
            from app.services.reputation_service import recalculate_reputation
            await recalculate_reputation(db, escrow.contractor_id)
        except Exception:
            pass
        await db.commit()
    except ValueError as e:
        return RedirectResponse(url=f"/dashboard/customer?error={e}", status_code=302)

    return RedirectResponse(url="/dashboard/customer?released=1", status_code=302)


@router.post("/integrations/connect")
async def connect_integration(
    request: Request,
    platform: str = Form(...),
    platform_account_id: str = Form(...),
    access_token: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "contractor":
        return RedirectResponse(url="/")

    integration = OmnichannelIntegration(
        contractor_id=current_user.id,
        platform=platform,
        platform_account_id=platform_account_id,
        access_token=access_token,
        is_active=True,
    )
    db.add(integration)
    await db.commit()

    # For Telegram: auto-set webhook so messages + inline keyboard buttons work.
    # The bot token is embedded in the URL path so the inbound handler can match
    # the integration by its token (Telegram posts to the bot, not a chat id).
    if platform == "telegram":
        try:
            import httpx
            base_url = str(request.base_url).rstrip("/")
            webhook_url = f"{base_url}/api/v1/webhooks/telegram/{access_token}"
            async with httpx.AsyncClient() as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{access_token}/setWebhook",
                    params={"url": webhook_url},
                )
                result = resp.json()
                if result.get("ok"):
                    print(f"[Telegram] Webhook set to {webhook_url}")
                else:
                    print(f"[Telegram] Webhook setup failed: {result}")
        except Exception as e:
            print(f"[Telegram] Webhook setup error: {e}")

    return RedirectResponse(url="/integrations?saved=integration", status_code=302)


@router.post("/integrations/{integration_id}/toggle")
async def toggle_integration(
    integration_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "contractor":
        return RedirectResponse(url="/")

    result = await db.exec(
        select(OmnichannelIntegration).where(
            OmnichannelIntegration.id == integration_id,
            OmnichannelIntegration.contractor_id == current_user.id,
        )
    )
    integration = result.first()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    integration.is_active = not integration.is_active
    db.add(integration)
    await db.commit()
    return RedirectResponse(url="/integrations", status_code=302)


@router.post("/integrations/{integration_id}/test")
async def test_integration(
    integration_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Verify an integration's credentials by pinging the platform.

    For Telegram we call `getMe` with the stored bot token; success means the
    token is valid and the webhook can deliver. Returns to /integrations with a
    flash message (success/error)."""
    if current_user.role != "contractor":
        return RedirectResponse(url="/")

    result = await db.exec(
        select(OmnichannelIntegration).where(
            OmnichannelIntegration.id == integration_id,
            OmnichannelIntegration.contractor_id == current_user.id,
        )
    )
    integration = result.first()
    if not integration:
        raise HTTPException(status_code=404, detail="Integration not found")

    try:
        import httpx
        if integration.platform == "telegram":
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.telegram.org/bot{integration.access_token}/getMe"
                )
                data = resp.json()
            if not data.get("ok"):
                return RedirectResponse(
                    url=f"/integrations?error=Telegram+error:+'{data.get('description', 'unknown')}'",
                    status_code=302,
                )
            bot = data.get("result", {})
            name = bot.get("username", "bot")
            return RedirectResponse(
                url=f"/integrations?success=Connected+to+@{name}+—+webhook+active", status_code=302
            )
        elif integration.platform in ("whatsapp", "messenger"):
            # Token presence is the only lightweight check we can do without a full Graph call.
            if not integration.access_token:
                return RedirectResponse(url="/integrations?error=Missing+access+token", status_code=302)
            return RedirectResponse(url="/integrations?success=Token+present+(Meta+webhooks+need+verify)", status_code=302)
        else:
            return RedirectResponse(url=f"/integrations?error=Unknown+platform", status_code=302)
    except Exception as e:
        return RedirectResponse(url=f"/integrations?error={str(e)[:120]}", status_code=302)

@router.get("/admin", response_class=HTMLResponse)
async def admin_dashboard(request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "admin":
        return RedirectResponse(url="/")
        
    audit_logs = []
    total_matches = total_reroutes = total_omnichannel_replies = avg_latency_ms = 0

    if AIOperationsAuditLog is not None:
        result = await db.exec(select(AIOperationsAuditLog).order_by(AIOperationsAuditLog.timestamp.desc()))
        audit_logs = result.all()
        total_matches = len([log for log in audit_logs if log.action_type == "triage_and_match"])
        total_reroutes = len([log for log in audit_logs if log.action_type == "auto_reroute"])
        total_omnichannel_replies = len([log for log in audit_logs if log.action_type == "omnichannel_auto_reply"])
        latencies = [log.latency_ms for log in audit_logs if log.latency_ms is not None]
        avg_latency_ms = int(sum(latencies) / len(latencies)) if latencies else 0

    # Platform stats
    users_result = await db.exec(select(User))
    all_users = users_result.all()
    total_users = len(all_users)
    total_customers = len([u for u in all_users if u.role == "customer"])
    total_contractors = len([u for u in all_users if u.role == "contractor"])
    verified_contractors = len([u for u in all_users if u.role == "contractor" and u.verification_level and u.verification_level != "none"])
    premium_contractors = len([u for u in all_users if u.role == "contractor" and subscription_service.is_premium(u)])

    jobs_result = await db.exec(select(Job))
    all_jobs = list(jobs_result.all())
    all_jobs.sort(key=lambda j: j.created_at or datetime.min, reverse=True)
    total_jobs = len(all_jobs)
    open_jobs = len([j for j in all_jobs if j.status == "open"])
    booked_jobs = len([j for j in all_jobs if j.status == "booked"])
    completed_jobs = len([j for j in all_jobs if j.status == "completed"])
    in_progress_jobs = len([j for j in all_jobs if j.status == "in_progress"])

    escrows_result = await db.exec(select(Escrow))
    all_escrows = list(escrows_result.all())
    all_escrows.sort(key=lambda e: e.id or 0, reverse=True)
    total_escrows = len(all_escrows)
    held_escrows = len([e for e in all_escrows if e.status == "held"])
    released_escrows = len([e for e in all_escrows if e.status == "released"])
    disputed_escrows = len([e for e in all_escrows if e.status == "disputed"])

    disputes_result = await db.exec(select(Dispute).order_by(Dispute.created_at.desc()))
    all_disputes = list(disputes_result.all())
    pending_disputes = len([d for d in all_disputes if d.status != "resolved"])

    # Verification requests (with contractor loaded). Premium contractors get
    # priority review — sorted premium-first, then newest-first within each group.
    # Pending requests sort above resolved ones for ops speed.
    vr_result = await db.exec(
        select(VerificationRequest)
        .options(selectinload(VerificationRequest.contractor))
    )
    all_verifications = list(vr_result.all())
    all_verifications.sort(
        key=lambda v: (
            0 if v.status == "pending" else 1,
            0 if (v.contractor and subscription_service.is_premium(v.contractor)) else 1,
            -(v.created_at.timestamp() if v.created_at else 0),
        )
    )
    pending_verifications = len([v for v in all_verifications if v.status == "pending"])

    users_by_id = {u.id: u for u in all_users}
    # Stable display order: admins → contractors → customers, then name
    role_rank = {"admin": 0, "contractor": 1, "customer": 2}
    all_users_sorted = sorted(
        all_users,
        key=lambda u: (role_rank.get(u.role, 9), (u.full_name or "").lower()),
    )

    return templates.TemplateResponse(request=request, name="admin_dashboard.html", context={
        "request": request,
        "current_user": current_user,
        "audit_logs": audit_logs[:50],
        "total_matches": total_matches,
        "total_reroutes": total_reroutes,
        "total_omnichannel_replies": total_omnichannel_replies,
        "avg_latency_ms": avg_latency_ms,
        "all_users": all_users_sorted,
        "users_by_id": users_by_id,
        "total_users": total_users,
        "total_customers": total_customers,
        "total_contractors": total_contractors,
        "verified_contractors": verified_contractors,
        "premium_contractors": premium_contractors,
        "subscription_service": subscription_service,
        "all_jobs": all_jobs,
        "total_jobs": total_jobs,
        "open_jobs": open_jobs,
        "booked_jobs": booked_jobs,
        "completed_jobs": completed_jobs,
        "in_progress_jobs": in_progress_jobs,
        "all_escrows": all_escrows,
        "total_escrows": total_escrows,
        "held_escrows": held_escrows,
        "released_escrows": released_escrows,
        "disputed_escrows": disputed_escrows,
        "all_disputes": all_disputes,
        "pending_disputes": pending_disputes,
        "all_verifications": all_verifications,
        "pending_verifications": pending_verifications,
        "format_location": format_location,
    })


@router.post("/admin/user/{user_id}/verify")
async def admin_verify_user(
    user_id: int,
    verification_level: str = Form(default="bronze"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        return RedirectResponse(url="/")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    user.verification_level = verification_level
    db.add(user)
    await db.commit()
    return RedirectResponse(
        url="/admin?tab=users&success=Verification+level+updated",
        status_code=302,
    )


@router.post("/admin/verification/{req_id}/approve")
async def admin_approve_verification(
    req_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        return RedirectResponse(url="/")
    req = await db.get(VerificationRequest, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != "pending":
        return RedirectResponse(url="/admin?tab=verifications&info=Already+reviewed", status_code=302)

    from datetime import datetime as _dt
    req.status = "approved"
    req.reviewed_by = current_user.id
    req.reviewed_at = _dt.utcnow()

    contractor = await db.get(User, req.contractor_id)
    if contractor:
        contractor.verification_level = req.requested_level
        db.add(contractor)
    db.add(req)
    await db.commit()
    return RedirectResponse(
        url="/admin?tab=verifications&success=Verification+approved",
        status_code=302,
    )


@router.post("/admin/verification/{req_id}/reject")
async def admin_reject_verification(
    req_id: int,
    review_notes: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        return RedirectResponse(url="/")
    req = await db.get(VerificationRequest, req_id)
    if not req:
        raise HTTPException(status_code=404, detail="Request not found")
    if req.status != "pending":
        return RedirectResponse(url="/admin?tab=verifications&info=Already+reviewed", status_code=302)

    from datetime import datetime as _dt
    req.status = "rejected"
    req.review_notes = review_notes.strip() or None
    req.reviewed_by = current_user.id
    req.reviewed_at = _dt.utcnow()
    db.add(req)
    await db.commit()
    return RedirectResponse(
        url="/admin?tab=verifications&success=Verification+rejected",
        status_code=302,
    )


@router.post("/admin/user/{user_id}/toggle-availability")
async def admin_toggle_availability(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        return RedirectResponse(url="/")
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    cycle = {"available": "away", "away": "busy", "busy": "vacation", "vacation": "available"}
    user.availability_status = cycle.get(user.availability_status, "available")
    db.add(user)
    await db.commit()
    return RedirectResponse(
        url=f"/admin?tab=users&success=Availability+set+to+{user.availability_status}",
        status_code=302,
    )


@router.post("/admin/dispute/{dispute_id}/resolve")
async def admin_resolve_dispute(
    dispute_id: int,
    resolution: str = Form(...),
    refund_pct: float = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        return RedirectResponse(url="/")
    dispute = await db.get(Dispute, dispute_id)
    if not dispute:
        raise HTTPException(status_code=404, detail="Dispute not found")
    if dispute.status == "resolved":
        return RedirectResponse(url="/admin?tab=disputes&info=Already+resolved", status_code=302)

    from app.services.escrow_service import resolve_dispute as resolve_escrow_dispute
    dispute = await resolve_escrow_dispute(db, dispute, resolution, refund_pct, current_user.id)
    await db.commit()
    return RedirectResponse(
        url="/admin?tab=disputes&success=Dispute+resolved",
        status_code=302,
    )


@router.post("/admin/escrow/{escrow_id}/release")
async def admin_release_escrow(
    escrow_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        return RedirectResponse(url="/")
    escrow = await db.get(Escrow, escrow_id)
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    from app.services.escrow_service import release_escrow
    from app.services.reputation_service import recalculate_reputation
    try:
        escrow = await release_escrow(db, escrow)
        job = await db.get(Job, escrow.job_id)
        if job:
            job.status = "completed"
            db.add(job)
        try:
            await recalculate_reputation(db, escrow.contractor_id)
        except Exception:
            pass
        await db.commit()
        return RedirectResponse(
            url="/admin?tab=escrows&success=Escrow+released+to+contractor",
            status_code=302,
        )
    except ValueError as e:
        return RedirectResponse(
            url=f"/admin?tab=escrows&error={str(e)[:120]}",
            status_code=302,
        )


@router.post("/admin/escrow/{escrow_id}/refund")
async def admin_refund_escrow(
    escrow_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    if current_user.role != "admin":
        return RedirectResponse(url="/")
    escrow = await db.get(Escrow, escrow_id)
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    from app.services.escrow_service import refund_escrow
    try:
        escrow = await refund_escrow(db, escrow, reason="admin_refund")
        await db.commit()
    except ValueError as e:
        return RedirectResponse(url=f"/admin?tab=escrows&error={str(e)[:120]}", status_code=302)
    return RedirectResponse(
        url="/admin?tab=escrows&success=Escrow+refunded+to+customer",
        status_code=302,
    )


@router.post("/jobs/{job_id}/start")
async def web_start_job(job_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "contractor":
        return RedirectResponse(url="/")
    job = await db.get(Job, job_id)
    if job and job.assigned_contractor_id == current_user.id and job.status == "booked":
        job.status = "in_progress"
        job.started_at = datetime.utcnow()
        db.add(job)
        from app.services.job_action_service import log_job_action
        try:
            await log_job_action(db, job_id, current_user.id, "started")
        except Exception:
            pass
        await db.commit()
    return RedirectResponse(url="/dashboard/contractor", status_code=302)


@router.post("/jobs/{job_id}/mark-complete")
async def web_mark_complete(job_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "contractor":
        return RedirectResponse(url="/")
    job = await db.get(Job, job_id)
    if job and job.assigned_contractor_id == current_user.id and job.status == "in_progress":
        job.status = "completed_pending"
        job.completed_at = datetime.utcnow()
        db.add(job)
        from app.services.job_action_service import log_job_action
        try:
            await log_job_action(db, job_id, current_user.id, "marked_complete")
        except Exception:
            pass
        await db.commit()
    return RedirectResponse(url="/dashboard/contractor", status_code=302)


@router.post("/jobs/{job_id}/confirm")
async def web_confirm_job(job_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "customer":
        return RedirectResponse(url="/")
    # Delegate to the API action endpoint
    from app.api.v1.endpoints.jobs import job_action
    try:
        await job_action(job_id, "confirm", current_user, db)
    except Exception:
        pass
    return RedirectResponse(url="/dashboard/customer", status_code=302)


@router.post("/jobs/{job_id}/cancel")
async def web_cancel_job(job_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Customer cancels a booking (before/after funding). Refunds escrow if held."""
    if current_user.role != "customer":
        return RedirectResponse(url="/")
    job = await db.get(Job, job_id)
    if not job or job.customer_id != current_user.id:
        return RedirectResponse(url="/dashboard/customer?error=job_not_found", status_code=302)
    if job.status not in ("booked", "in_progress", "completed_pending"):
        return RedirectResponse(url="/dashboard/customer?error=cannot_cancel", status_code=302)

    # Refund the customer if the escrow was funded
    result = await db.exec(select(Escrow).where(Escrow.job_id == job_id))
    escrow = result.first()
    if escrow and escrow.status == "held":
        from app.services.escrow_service import refund_escrow
        try:
            await refund_escrow(db, escrow, reason="customer_cancelled")
        except ValueError:
            pass

    job.status = "cancelled"
    db.add(job)
    await db.commit()
    return RedirectResponse(url="/dashboard/customer?cancelled=1", status_code=302)



@router.get("/cctv/intake", response_class=HTMLResponse)
async def cctv_intake_page(
    request: Request, current_user: User = Depends(get_current_user)
):
    """Phase 1 entry point: customer describes a CCTV/security need in plain
    language; the page calls /api/v1/cctv/intake to produce a structured brief
    and matched installers."""
    if current_user.role != "customer":
        return RedirectResponse(url="/")
    return templates.TemplateResponse(
        request=request, name="cctv_intake.html", context={"current_user": current_user}
    )


@router.get("/dashboard/customer", response_class=HTMLResponse)
async def customer_dashboard(request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "customer":
        return RedirectResponse(url="/")
        
    result = await db.exec(select(Job).options(selectinload(Job.assigned_contractor)).where(Job.customer_id == current_user.id).order_by(Job.created_at.desc()))
    customer_jobs = result.all()
    
    # Load escrow data for each job
    escrow_map = {}
    for job in customer_jobs:
        escrow_result = await db.exec(select(Escrow).where(Escrow.job_id == job.id))
        escrow = escrow_result.first()
        if escrow:
            escrow_map[job.id] = escrow

    # Which of these jobs already have a review
    job_ids = [j.id for j in customer_jobs if j.id is not None]
    reviewed_job_ids = set()
    if job_ids:
        reviews_result = await db.exec(select(Review).where(Review.job_id.in_(job_ids)))
        reviewed_job_ids = {r.job_id for r in reviews_result.all()}
        
    # Load conversation mapping for chat buttons
    conversation_map = {}
    if job_ids:
        conv_result = await db.exec(select(Conversation).where(Conversation.job_id.in_(job_ids)))
        for conv in conv_result.all():
            conversation_map[conv.job_id] = conv.id

    # Dispute status by job (for open disputes UI)
    dispute_map = {}
    if job_ids:
        disp_result = await db.exec(select(Dispute).where(Dispute.job_id.in_(job_ids)))
        for d in disp_result.all():
            dispute_map[d.job_id] = d

    return templates.TemplateResponse(request=request, name="customer_dashboard.html", context={
        "request": request,
        "current_user": current_user,
        "customer_jobs": customer_jobs,
        "escrow_map": escrow_map,
        "conversation_map": conversation_map,
        "dispute_map": dispute_map,
        "reviewed_job_ids": reviewed_job_ids,
        "active_statuses": ["open", "matched", "booked", "in_progress", "completed_pending"],
        "flash": _flash_from_query(request),
        "charge_currency": settings.PAYSTACK_CURRENCY if settings.active_processor() == "paystack" else settings.PAYMENT_CURRENCY,
        "format_location": format_location,
        "voice_enabled": bool(settings.CALL_E_API_KEY),
    })

@router.post("/jobs/{job_id}/review")
async def submit_review(
    job_id: int,
    rating: int = Form(...),
    comment: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Customer leaves a review on a completed job. Recomputes contractor reputation."""
    if current_user.role != "customer":
        return RedirectResponse(url="/")

    job = await db.get(Job, job_id)
    if not job or job.customer_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="You can only review completed jobs")
    if not job.assigned_contractor_id:
        raise HTTPException(status_code=400, detail="No contractor assigned to this job")

    # Prevent duplicate reviews for the same job
    existing = await db.exec(select(Review).where(Review.job_id == job_id))
    if existing.first():
        return RedirectResponse(url="/dashboard/customer", status_code=302)

    rating = max(1, min(5, rating))
    review = Review(
        job_id=job_id,
        contractor_id=job.assigned_contractor_id,
        rating=rating,
        comment=comment.strip() or None,
    )
    db.add(review)
    await db.flush()

    # Recompute reputation from the new review
    from app.services.reputation_service import recalculate_reputation
    try:
        await recalculate_reputation(db, job.assigned_contractor_id)
    except Exception:
        pass

    await db.commit()
    return RedirectResponse(url="/dashboard/customer", status_code=302)


@router.get("/dashboard/contractor", response_class=HTMLResponse)
async def contractor_dashboard(request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "contractor":
        return RedirectResponse(url="/")

    # Self-heal expired trial/subscription
    current_user = await subscription_service.enforce_expiry(db, current_user)

    # Get active dispatches (booked / in_progress / awaiting confirmation)
    result = await db.exec(
        select(Job).options(selectinload(Job.customer)).where(
            Job.assigned_contractor_id == current_user.id,
            Job.status.in_(["booked", "in_progress", "completed_pending"]),
        ).order_by(Job.created_at.desc())
    )
    active_dispatches = result.all()
    
    jobs_today = len(active_dispatches) # Simplification: assuming all active are today's capacity
    
    # Load escrow data for each dispatch
    escrow_map = {}
    dispute_map = {}
    total_earnings = 0
    for job in active_dispatches:
        escrow_result = await db.exec(select(Escrow).where(Escrow.job_id == job.id))
        escrow = escrow_result.first()
        if escrow:
            escrow_map[job.id] = escrow
            if escrow.status in ("released", "held"):
                total_earnings += float(escrow.contractor_payout)
            d_result = await db.exec(select(Dispute).where(Dispute.escrow_id == escrow.id))
            d = d_result.first()
            if d:
                dispute_map[job.id] = d
    
    # Latest verification request (for the trust/verification card)
    vr_result = await db.exec(
        select(VerificationRequest)
        .where(VerificationRequest.contractor_id == current_user.id)
        .order_by(VerificationRequest.created_at.desc())
    )
    verification_request = vr_result.first()

    wallet = await wallet_service.get_wallet(db, current_user.id)
    is_boosted = bool(current_user.boosted_until and current_user.boosted_until > datetime.utcnow())
    qs = request.query_params
    flash = None
    if qs.get("boosted"):
        flash = {"kind": "success", "message": "Profile boosted! You'll appear at the top of search results for 24 hours."}
    elif qs.get("success"):
        flash = {"kind": "success", "message": qs["success"]}
    elif qs.get("error"):
        flash = {"kind": "error", "message": qs["error"].replace("_", " ").capitalize()}

    return templates.TemplateResponse(request=request, name="contractor_dashboard.html", context={
        "request": request,
        "current_user": current_user,
        "active_dispatches": active_dispatches,
        "jobs_today": jobs_today,
        "escrow_map": escrow_map,
        "dispute_map": dispute_map,
        "total_earnings": total_earnings,
        "verification_request": verification_request,
        "effective_tier": subscription_service.effective_tier(current_user),
        "is_premium": subscription_service.is_premium(current_user),
        "trial_days_remaining": subscription_service.trial_days_remaining(current_user),
        "wallet_balance": float(wallet.available_balance),
        "boost_price": settings.BOOST_PRICE,
        "is_boosted": is_boosted,
        "boosted_until": current_user.boosted_until,
        "stripe_connected": bool(current_user.stripe_account_id),
        "paystack_connected": bool(current_user.paystack_recipient_code),
        "charge_currency": settings.PAYSTACK_CURRENCY if settings.active_processor() == "paystack" else settings.PAYMENT_CURRENCY,
        "flash": flash,
        "format_location": format_location
    })

@router.get("/messages", response_class=HTMLResponse)
async def messages_list(request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role not in ("customer", "contractor"):
        return RedirectResponse(url="/")

    from app.services.notification_service import build_conversation_list
    show_archived = request.query_params.get("filter") == "archived"
    conversations = await build_conversation_list(
        db, current_user, include_archived=show_archived
    )
    if show_archived:
        conversations = [c for c in conversations if c.get("is_archived")]
    else:
        conversations = [c for c in conversations if not c.get("is_archived")]

    return templates.TemplateResponse(request=request, name="messages.html", context={
        "request": request,
        "current_user": current_user,
        "conversations": conversations,
        "active_conversation_id": None,
        "inbox_filter": "archived" if show_archived else "active",
    })


@router.get("/messages/start/{contractor_id}", response_class=HTMLResponse)
async def start_conversation(request: Request, contractor_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "customer":
        return RedirectResponse(url="/")

    # Only reuse a conversation whose job is still ACTIVE (booked or in_progress).
    # Completed / cancelled jobs should get a brand-new booking so the customer
    # isn't stuck inside an old finished chat.
    active_statuses = ["booked", "in_progress", "matched"]
    active_conv_result = await db.exec(
        select(Conversation)
        .join(Job, Job.id == Conversation.job_id)
        .where(
            Conversation.customer_id == current_user.id,
            Conversation.contractor_id == contractor_id,
            Job.status.in_(active_statuses),
        )
        .order_by(Conversation.id.desc())
    )
    active_conv = active_conv_result.first()
    if active_conv:
        return RedirectResponse(url=f"/chat/{active_conv.id}")

    # No active conversation — create a fresh job + conversation.
    # This also covers the "re-book same contractor after completion" case.
    contractor = await db.get(User, contractor_id)
    if not contractor or contractor.role != "contractor":
        raise HTTPException(status_code=404, detail="Contractor not found")

    job = Job(
        customer_id=current_user.id,
        assigned_contractor_id=contractor_id,
        description=f"Service request for {contractor.profession or 'job'}",
        status="booked",
    )
    db.add(job)
    await db.flush()

    # Create escrow so the payment page is ready
    from app.services.escrow_service import create_escrow
    amount = Decimal(str(contractor.base_pricing or 50.00))
    await create_escrow(db, job, current_user, contractor, amount)

    new_conv = Conversation(id=job.id, job_id=job.id, customer_id=current_user.id, contractor_id=contractor_id)
    db.add(new_conv)
    await db.commit()
    await db.refresh(new_conv)

    return RedirectResponse(url=f"/chat/{new_conv.id}")


@router.get("/chat", response_class=HTMLResponse)
async def chat_landing(current_user: User = Depends(get_current_user)):
    return RedirectResponse(url="/messages")

@router.get("/chat/{conversation_id}", response_class=HTMLResponse)
async def chat_page(conversation_id: int, request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    result = await db.exec(select(Conversation).where(Conversation.id == conversation_id))
    conversation = result.first()
    
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
        
    if current_user.id not in [conversation.customer_id, conversation.contractor_id]:
        raise HTTPException(status_code=403, detail="Not authorized to view this chat")

    from app.services.notification_service import build_conversation_list, mark_conversation_read
    await mark_conversation_read(db, conversation, current_user.id)
        
    partner_id = conversation.contractor_id if current_user.id == conversation.customer_id else conversation.customer_id
    partner_result = await db.exec(select(User).where(User.id == partner_id))
    partner = partner_result.first()
    
    msg_result = await db.exec(select(DirectMessage).where(DirectMessage.conversation_id == conversation_id).order_by(DirectMessage.timestamp.asc()))
    past_messages = msg_result.all()

    # Partner's read cursor — used for historic ✓✓ / read state on own messages
    if current_user.id == conversation.customer_id:
        partner_last_read_at = getattr(conversation, "last_read_at_contractor", None)
    else:
        partner_last_read_at = getattr(conversation, "last_read_at_customer", None)

    job = await db.get(Job, conversation.job_id)
    escrow = None
    dispute = None
    if job:
        e_result = await db.exec(select(Escrow).where(Escrow.job_id == job.id))
        escrow = e_result.first()
        if escrow:
            d_result = await db.exec(select(Dispute).where(Dispute.escrow_id == escrow.id))
            dispute = d_result.first()

    # Review status for post-job prompt (customers only)
    has_review = False
    if job and job.status == "completed" and current_user.id == conversation.customer_id:
        rev = (await db.exec(select(Review).where(Review.job_id == job.id))).first()
        has_review = rev is not None

    is_customer = current_user.id == conversation.customer_id
    conv_archived = bool(
        conversation.archived_by_customer if is_customer else conversation.archived_by_contractor
    )
    conv_muted = bool(
        conversation.muted_by_customer if is_customer else conversation.muted_by_contractor
    )

    conversations = await build_conversation_list(db, current_user, include_archived=True)
    # Active thread was just marked read — zero its unread in the sidebar
    for c in conversations:
        if c["id"] == conversation_id:
            c["unread_count"] = 0

    job_location = format_location(job) if job else "—"
    flash = _flash_from_query(request)

    return templates.TemplateResponse(request=request, name="chat.html", context={
        "request": request,
        "current_user": current_user,
        "conversation": conversation,
        "partner": partner,
        "partner_id": partner_id,
        "partner_last_read_at": partner_last_read_at,
        "past_messages": past_messages,
        "job": job,
        "escrow": escrow,
        "dispute": dispute,
        "conversations": conversations,
        "active_conversation_id": conversation_id,
        "has_review": has_review,
        "conv_archived": conv_archived,
        "conv_muted": conv_muted,
        "job_location": job_location,
        "format_location": format_location,
        "flash": flash,
    })


@router.get("/drafts")
async def drafts_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Contractor page to view and manage pending AI drafts."""
    if current_user.role != "contractor":
        return RedirectResponse(url="/")

    result = await db.exec(
        select(AIDraft).where(
            AIDraft.contractor_id == current_user.id,
            AIDraft.status == "pending",
        ).order_by(AIDraft.created_at.desc())
    )
    pending_drafts = result.all()

    # Enrich with conversation details
    drafts_with_context = []
    for draft in pending_drafts:
        conv = await db.get(Conversation, draft.conversation_id)
        partner = None
        if conv:
            partner = await db.get(User, conv.customer_id)
        drafts_with_context.append({
            "draft": draft,
            "conversation": conv,
            "partner": partner,
        })

    return templates.TemplateResponse(request=request, name="drafts.html", context={
        "request": request,
        "current_user": current_user,
        "drafts_with_context": drafts_with_context,
    })


# ─────────────────────────────────────────────────────────────────────────────
# PAYMENT METHODS
# ─────────────────────────────────────────────────────────────────────────────
# (CURRENCY_SYMBOLS and COUNTRY_CURRENCY_MAP are defined at the top of this
#  module so all route handlers can reference them without ordering issues.)


@router.get("/payment-methods", response_class=HTMLResponse)
async def payment_methods_page(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.all_models import PaymentMethod
    result = await db.exec(select(PaymentMethod).where(PaymentMethod.user_id == current_user.id))
    methods = result.all()
    return templates.TemplateResponse(request=request, name="payment_methods.html", context={
        "request": request,
        "current_user": current_user,
        "payment_methods": methods,
    })


@router.post("/payment-methods", response_class=HTMLResponse)
async def add_payment_method(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    type: str = Form(default="card"),
    provider: str = Form(default="visa"),
    display_name: str = Form(default=""),
    last4: Optional[str] = Form(default=None),
    brand: Optional[str] = Form(default=None),
    expiry: Optional[str] = Form(default=None),
    account_name: Optional[str] = Form(default=None),
    bank_name: Optional[str] = Form(default=None),
    phone: Optional[str] = Form(default=None),
):
    from app.models.all_models import PaymentMethod
    method = PaymentMethod(
        user_id=current_user.id,
        type=type, provider=provider, display_name=display_name,
        last4=last4, brand=brand, expiry=expiry,
        account_name=account_name, bank_name=bank_name, phone=phone,
    )
    db.add(method)
    await db.commit()
    return RedirectResponse(url="/payment-methods?success=Payment+method+added", status_code=303)


@router.post("/payment-methods/{method_id}/delete", response_class=HTMLResponse)
async def delete_payment_method(
    request: Request,
    method_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.all_models import PaymentMethod
    method = await db.get(PaymentMethod, method_id)
    if method and method.user_id == current_user.id:
        await db.delete(method)
        await db.commit()
    return RedirectResponse(url="/payment-methods", status_code=303)


@router.post("/payment-methods/{method_id}/default", response_class=HTMLResponse)
async def set_default_payment_method(
    request: Request,
    method_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.models.all_models import PaymentMethod
    # Unset all defaults
    result = await db.exec(select(PaymentMethod).where(PaymentMethod.user_id == current_user.id))
    for m in result.all():
        m.is_default = (m.id == method_id)
        db.add(m)
    await db.commit()
    return RedirectResponse(url="/payment-methods", status_code=303)


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER SETTINGS
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/settings", response_class=HTMLResponse)
async def customer_settings_page(
    request: Request,
    current_user: User = Depends(get_current_user),
):
    flash = _flash_from_query(request)
    return templates.TemplateResponse(request=request, name="customer_settings.html", context={
        "request": request,
        "current_user": current_user,
        "flash": flash,
        "paystack_live": settings.paystack_live,
    })


@router.post("/settings/profile", response_class=HTMLResponse)
async def update_profile(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    full_name: str = Form(default=""),
    phone: Optional[str] = Form(default=None),
    city: Optional[str] = Form(default=None),
    country: Optional[str] = Form(default=None),
):
    if full_name:
        current_user.full_name = full_name
    if phone is not None:
        current_user.phone = phone
    if city is not None:
        current_user.city = city
    if country is not None:
        current_user.country = country
    db.add(current_user)
    await db.commit()
    return RedirectResponse(url="/settings?success=Profile+updated", status_code=303)


_AVATAR_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp"}


@router.post("/settings/avatar", response_class=HTMLResponse)
async def update_avatar(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    avatar: UploadFile = File(...),
):
    from app.services.upload_service import save_upload
    data = await avatar.read()
    try:
        url = await save_upload(
            data, avatar.filename or "avatar",
            allowlist=_AVATAR_EXT, max_bytes=5 * 1024 * 1024, folder="avatars",
        )
    except ValueError as e:
        return RedirectResponse(url=f"/settings?error={str(e)}", status_code=303)
    current_user.avatar_url = url
    db.add(current_user)
    await db.commit()
    return RedirectResponse(url="/settings?success=Photo+updated", status_code=303)


@router.post("/settings/notifications", response_class=HTMLResponse)
async def update_notifications(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Persist notification toggles. Checkboxes only POST when checked."""
    form = await request.form()
    keys = ["email-notifications", "sms-notifications", "job-updates", "promotions"]
    prefs = {k: (k in form) for k in keys}
    current_user.notification_prefs = prefs
    db.add(current_user)
    await db.commit()
    return RedirectResponse(url="/settings?success=Preferences+saved", status_code=303)


@router.post("/settings/password", response_class=HTMLResponse)
async def change_password(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    current_password: str = Form(...),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
):
    if not verify_password(current_password, current_user.hashed_password):
        return RedirectResponse(url="/settings?error=Current+password+is+incorrect", status_code=303)
    if len(new_password) < 8:
        return RedirectResponse(url="/settings?error=New+password+must+be+at+least+8+characters", status_code=303)
    if new_password != confirm_password:
        return RedirectResponse(url="/settings?error=Passwords+do+not+match", status_code=303)
    current_user.hashed_password = get_password_hash(new_password)
    db.add(current_user)
    await db.commit()
    return RedirectResponse(url="/settings?success=Password+updated", status_code=303)


@router.post("/settings/delete", response_class=HTMLResponse)
async def delete_account(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    confirm_password: str = Form(...),
):
    """Soft-delete: deactivate the account, scramble login, and clear the session."""
    if not verify_password(confirm_password, current_user.hashed_password):
        return RedirectResponse(url="/settings?error=Password+is+incorrect", status_code=303)
    import uuid as _uuid
    current_user.is_active = False
    current_user.availability_status = "Vacation"
    # Invalidate credentials so the account can no longer log in.
    current_user.hashed_password = get_password_hash(_uuid.uuid4().hex)
    current_user.email = f"deleted_{current_user.id}_{_uuid.uuid4().hex[:8]}@deleted.local"
    db.add(current_user)
    await db.commit()
    resp = RedirectResponse(url="/?success=Account+deleted", status_code=303)
    resp.delete_cookie("access_token")
    return resp


@router.post("/settings/payout", response_class=HTMLResponse)
async def update_payout_method(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    account_name: str = Form(default=""),
    account_number: str = Form(default=""),
    bank_code: str = Form(default=""),
    bank_name: str = Form(default=""),
):
    """Contractor sets their bank details for Paystack payouts.

    Creates a Paystack transfer recipient and stores the recipient code on
    the user so future escrow releases can pay out via Paystack Transfer.
    """
    if current_user.role != "contractor":
        return RedirectResponse(url="/settings?error=Only+contractors+can+set+payout+details", status_code=302)
    if not account_name or not account_number or not bank_code:
        return RedirectResponse(url="/settings?error=Account+name,+number+and+bank+code+are+required", status_code=302)
    if len(account_number) < 10:
        return RedirectResponse(url="/settings?error=Invalid+account+number", status_code=302)

    from urllib.parse import quote
    if settings.paystack_live:
        from app.services import payment_gateway as pgw
        import asyncio
        try:
            result = await asyncio.wait_for(
                asyncio.to_thread(pgw.create_paystack_recipient, account_name, account_number, bank_code),
                timeout=15,
            )
        except asyncio.TimeoutError:
            return RedirectResponse(url="/settings?error=Paystack+timed+out.+Please+try+again.", status_code=302)

        if not result.get("success"):
            return RedirectResponse(
                url=f"/settings?error=Failed+to+create+payout+recipient:+{quote(result.get('error', 'unknown error'))}",
                status_code=302,
            )
        current_user.paystack_recipient_code = result.get("recipient_code")
    else:
        current_user.paystack_recipient_code = None

    current_user.payout_bank_name = bank_name
    current_user.payout_bank_code = bank_code
    current_user.payout_account_number = account_number
    current_user.payout_account_name = account_name
    db.add(current_user)
    await db.commit()
    msg = "Payout+method+saved." if not settings.paystack_live else "Payout+method+saved+and+verified+with+Paystack."
    return RedirectResponse(url=f"/settings?success={quote(msg)}", status_code=302)


# ─────────────────────────────────────────────────────────────────────────────
# STRIPE CONNECT ONBOARDING (contractor payouts)
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/contractor/stripe/connect")
async def stripe_connect(
    request: Request,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Start (or resume) Stripe Connect onboarding so the contractor can receive payouts."""
    if current_user.role != "contractor":
        return RedirectResponse(url="/", status_code=303)
    from app.services import payment_gateway

    if not current_user.stripe_account_id:
        acct = payment_gateway.create_connect_account(current_user.email)
        if not acct.get("success"):
            return RedirectResponse(url=f"/contractor/dashboard?error=Stripe+error", status_code=303)
        current_user.stripe_account_id = acct["account_id"]
        db.add(current_user)
        await db.commit()

    base = str(request.base_url).rstrip("/")
    link = payment_gateway.create_onboarding_link(
        current_user.stripe_account_id,
        return_url=f"{base}/contractor/stripe/return",
        refresh_url=f"{base}/contractor/stripe/connect",
    )
    if not link.get("success"):
        return RedirectResponse(url="/contractor/dashboard?error=Stripe+onboarding+failed", status_code=303)
    return RedirectResponse(url=link["url"], status_code=303)


@router.get("/contractor/stripe/return")
async def stripe_connect_return(current_user: User = Depends(get_current_user)):
    """Landing after Stripe onboarding (or the mock shortcut)."""
    return RedirectResponse(url="/contractor/dashboard?success=Payouts+connected", status_code=303)


# ─────────────────────────────────────────────────────────────────────────────
# CUSTOMER DISPUTE FILING
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/escrow/{job_id}/dispute", response_class=HTMLResponse)
async def file_dispute(
    request: Request,
    job_id: int,
    reason: str = Form(default=""),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    job = await db.get(Job, job_id)
    if not job or current_user.id not in (job.customer_id, job.assigned_contractor_id):
        raise HTTPException(status_code=403, detail="Forbidden")
    result = await db.exec(select(Escrow).where(Escrow.job_id == job_id))
    escrow = result.first()
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    try:
        from app.services.escrow_service import open_dispute, analyze_and_attach_dispute
        dispute = await open_dispute(db, escrow, current_user, reason or "Dispute filed")
        # Gather chat context for the AI arbitrator and persist its recommendation.
        conversation = (await db.exec(
            select(Conversation).where(Conversation.job_id == job_id)
        )).first()
        chat_history = []
        if conversation:
            msgs = (await db.exec(
                select(DirectMessage).where(DirectMessage.conversation_id == conversation.id)
                .order_by(DirectMessage.timestamp)
            )).all()
            chat_history = [
                {"role": "customer" if m.sender_id == job.customer_id else "contractor", "content": m.content}
                for m in msgs
            ]
        await analyze_and_attach_dispute(
            db, dispute, chat_history, job.description or "",
            str(escrow.total_amount),
        )
        await db.commit()
    except ValueError as e:
        dash = "/dashboard/customer" if current_user.role == "customer" else "/contractor/dashboard"
        return RedirectResponse(url=f"{dash}?error={str(e)}", status_code=303)
    conv = (await db.exec(select(Conversation).where(Conversation.job_id == job_id))).first()
    if conv:
        return RedirectResponse(url=f"/chat/{conv.id}?success=Dispute+filed", status_code=303)
    dash = "/dashboard/customer" if current_user.role == "customer" else "/contractor/dashboard"
    return RedirectResponse(url=f"{dash}?success=Dispute+filed", status_code=303)


# ─────────────────────────────────────────────────────────────────────────────
# ServiceSync Voice — AI phone dispatcher status page
# ─────────────────────────────────────────────────────────────────────────────
@router.get("/voice/{job_id}", response_class=HTMLResponse)
async def voice_dispatch_page(
    request: Request,
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Show the live status of CALL-E calls placed for a job and the ranked offers."""
    job = await db.get(Job, job_id)
    if not job or (job.customer_id != current_user.id and current_user.role != "admin"):
        raise HTTPException(status_code=404, detail="Job not found")

    raw_offers = DISPATCH_STATE.get(job_id, [])
    contractor_ids = [o.contractor_id for o in raw_offers]
    contractors_map = {}
    if contractor_ids:
        res = await db.exec(select(User).where(User.id.in_(contractor_ids)))
        contractors_map = {u.id: u for u in res.all()}

    offers = []
    for o in raw_offers:
        d = voice_offer_out(o)
        u = contractors_map.get(o.contractor_id)
        d["contractor_name"] = u.full_name if u else f"Contractor #{o.contractor_id}"
        d["profession"] = getattr(u, "profession", None)
        d["city"] = getattr(u, "city", None)
        d["country"] = getattr(u, "country", None)
        d["can_book"] = bool(o.result.availability and not o.error)
        offers.append(d)

    return templates.TemplateResponse(
        "voice_dispatch.html",
        {
            "request": request,
            "current_user": current_user,
            "job": job,
            "job_id": job_id,
            "offers": offers,
            "voice_enabled": bool(settings.CALL_E_API_KEY),
        },
    )
