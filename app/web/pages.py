from fastapi import APIRouter, Request, Depends, HTTPException, Form, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from sqlalchemy.orm import selectinload
from typing import Optional

from app.api.dependencies import get_current_user_optional, get_current_user, get_db
from app.models.all_models import User, Job, Conversation, DirectMessage, OmnichannelIntegration, Review, Escrow, Dispute, AIDraft
from app.core.config import settings
from pathlib import Path

try:
    from app.models.audit_log import AIOperationsAuditLog
except ImportError:
    AIOperationsAuditLog = None

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

def format_location(obj) -> str:
    if not obj:
        return "—"
    parts = [part for part in [getattr(obj, 'area', None), getattr(obj, 'city', None), getattr(obj, 'state_or_province', None), getattr(obj, 'country', None)] if part]
    if parts:
        return ", ".join(parts)
    return getattr(obj, 'zip_code', None) or getattr(obj, 'postal_code', None) or "—"

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
    return templates.TemplateResponse(request=request, name="search.html", context={"request": request, "current_user": current_user})


@router.get("/contractors", response_class=HTMLResponse)
async def contractor_listing(
    request: Request,
    profession: Optional[str] = None,
    city: Optional[str] = None,
    country: Optional[str] = None,
    current_user: Optional[User] = Depends(get_current_user_optional),
    db: AsyncSession = Depends(get_db),
):
    query = select(User).where(User.role == "contractor")
    if profession:
        query = query.where(User.profession == profession)
    if city:
        query = query.where(User.city == city)
    if country:
        query = query.where(User.country == country)
    result = await db.exec(query)
    contractors = result.all()
    return templates.TemplateResponse(request=request, name="contractor_listing.html", context={
        "request": request,
        "current_user": current_user,
        "contractors": contractors,
        "format_location": format_location,
        "filters": {"profession": profession, "city": city, "country": country},
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

    # For Telegram: auto-set webhook so inline keyboard buttons work
    if platform == "telegram":
        try:
            import httpx
            base_url = str(request.base_url).rstrip("/")
            webhook_url = f"{base_url}/api/v1/webhooks/telegram"
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

    jobs_result = await db.exec(select(Job))
    all_jobs = list(jobs_result.all())
    total_jobs = len(all_jobs)
    open_jobs = len([j for j in all_jobs if j.status == "open"])
    booked_jobs = len([j for j in all_jobs if j.status == "booked"])
    completed_jobs = len([j for j in all_jobs if j.status == "completed"])

    escrows_result = await db.exec(select(Escrow))
    all_escrows = list(escrows_result.all())
    total_escrows = len(all_escrows)
    held_escrows = len([e for e in all_escrows if e.status == "held"])
    released_escrows = len([e for e in all_escrows if e.status == "released"])
    disputed_escrows = len([e for e in all_escrows if e.status == "disputed"])

    disputes_result = await db.exec(select(Dispute).order_by(Dispute.created_at.desc()))
    all_disputes = list(disputes_result.all())
    pending_disputes = len([d for d in all_disputes if d.status != "resolved"])

    return templates.TemplateResponse(request=request, name="admin_dashboard.html", context={
        "request": request,
        "current_user": current_user,
        "audit_logs": audit_logs[:50],
        "total_matches": total_matches,
        "total_reroutes": total_reroutes,
        "total_omnichannel_replies": total_omnichannel_replies,
        "avg_latency_ms": avg_latency_ms,
        "all_users": all_users,
        "total_users": total_users,
        "total_customers": total_customers,
        "total_contractors": total_contractors,
        "verified_contractors": verified_contractors,
        "all_jobs": all_jobs,
        "total_jobs": total_jobs,
        "open_jobs": open_jobs,
        "booked_jobs": booked_jobs,
        "completed_jobs": completed_jobs,
        "all_escrows": all_escrows,
        "total_escrows": total_escrows,
        "held_escrows": held_escrows,
        "released_escrows": released_escrows,
        "disputed_escrows": disputed_escrows,
        "all_disputes": all_disputes,
        "pending_disputes": pending_disputes,
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
    return RedirectResponse(url="/admin?tab=users", status_code=302)


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
    return RedirectResponse(url="/admin?tab=users", status_code=302)


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
        return RedirectResponse(url="/admin?tab=disputes", status_code=302)

    from app.services.escrow_service import resolve_dispute as resolve_escrow_dispute
    dispute = await resolve_escrow_dispute(db, dispute, resolution, refund_pct, current_user.id)
    await db.commit()
    return RedirectResponse(url="/admin?tab=disputes", status_code=302)


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
    try:
        escrow = await release_escrow(db, escrow)
        job = await db.get(Job, escrow.job_id)
        if job:
            job.status = "completed"
            db.add(job)
        await db.commit()
    except ValueError:
        pass
    return RedirectResponse(url="/admin?tab=escrows", status_code=302)


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
    except ValueError:
        pass
    return RedirectResponse(url="/admin?tab=escrows", status_code=302)


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
    
    return templates.TemplateResponse(request=request, name="customer_dashboard.html", context={
        "request": request,
        "current_user": current_user,
        "customer_jobs": customer_jobs,
        "escrow_map": escrow_map,
        "format_location": format_location
    })

@router.get("/dashboard/contractor", response_class=HTMLResponse)
async def contractor_dashboard(request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "contractor":
        return RedirectResponse(url="/")
        
    # Get active dispatches (booked jobs assigned to this contractor)
    result = await db.exec(select(Job).options(selectinload(Job.customer)).where(Job.assigned_contractor_id == current_user.id, Job.status == "booked").order_by(Job.created_at.desc()))
    active_dispatches = result.all()
    
    jobs_today = len(active_dispatches) # Simplification: assuming all active are today's capacity
    
    # Load escrow data for each dispatch
    escrow_map = {}
    total_earnings = 0
    for job in active_dispatches:
        escrow_result = await db.exec(select(Escrow).where(Escrow.job_id == job.id))
        escrow = escrow_result.first()
        if escrow:
            escrow_map[job.id] = escrow
            if escrow.status in ("released", "held"):
                total_earnings += float(escrow.contractor_payout)
    
    return templates.TemplateResponse(request=request, name="contractor_dashboard.html", context={
        "request": request,
        "current_user": current_user,
        "active_dispatches": active_dispatches,
        "jobs_today": jobs_today,
        "escrow_map": escrow_map,
        "total_earnings": total_earnings,
        "format_location": format_location
    })

@router.get("/messages", response_class=HTMLResponse)
async def messages_list(request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role == "customer":
        query = select(Conversation).options(selectinload(Conversation.customer), selectinload(Conversation.contractor), selectinload(Conversation.messages)).where(Conversation.customer_id == current_user.id)
    elif current_user.role == "contractor":
        query = select(Conversation).options(selectinload(Conversation.customer), selectinload(Conversation.contractor), selectinload(Conversation.messages)).where(Conversation.contractor_id == current_user.id)
    else:
        return RedirectResponse(url="/")

    result = await db.exec(query.order_by(Conversation.created_at.desc()))
    conversations_raw = result.all()

    # Enrich with partner info and latest message
    conversations = []
    for conv in conversations_raw:
        partner_id = conv.contractor_id if current_user.id == conv.customer_id else conv.customer_id
        partner_result = await db.exec(select(User).where(User.id == partner_id))
        partner = partner_result.first()

        # Get job status
        job_result = await db.exec(select(Job).where(Job.id == conv.job_id))
        job = job_result.first()

        # Get latest message
        latest_msg = conv.messages[-1] if conv.messages else None

        conversations.append({
            "id": conv.id,
            "job_id": conv.job_id,
            "partner": partner,
            "job_status": job.status if job else None,
            "latest_message": latest_msg.content if latest_msg else None,
            "latest_message_time": latest_msg.timestamp.strftime('%b %d, %H:%M') if latest_msg else conv.created_at.strftime('%b %d'),
            "created_at": conv.created_at,
        })

    return templates.TemplateResponse(request=request, name="messages.html", context={
        "request": request,
        "current_user": current_user,
        "conversations": conversations,
    })


@router.get("/messages/start/{contractor_id}", response_class=HTMLResponse)
async def start_conversation(request: Request, contractor_id: int, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "customer":
        return RedirectResponse(url="/")

    # Find an existing conversation with this contractor
    existing = await db.exec(
        select(Conversation).where(
            Conversation.customer_id == current_user.id,
            Conversation.contractor_id == contractor_id
        )
    )
    conv = existing.first()
    if conv:
        return RedirectResponse(url=f"/chat/{conv.id}")

    # Find the most recent booked/matched job with this contractor
    job_result = await db.exec(
        select(Job).where(
            Job.customer_id == current_user.id,
            Job.assigned_contractor_id == contractor_id,
            Job.status.in_(["booked", "matched"])
        ).order_by(Job.created_at.desc())
    )
    job = job_result.first()

    if not job:
        # Create a placeholder job for this conversation
        job = Job(
            customer_id=current_user.id,
            assigned_contractor_id=contractor_id,
            description=f"Conversation with contractor",
            status="booked",
        )
        db.add(job)
        await db.commit()
        await db.refresh(job)

    # Create conversation
    new_conv = Conversation(job_id=job.id, customer_id=current_user.id, contractor_id=contractor_id)
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
        
    partner_id = conversation.contractor_id if current_user.id == conversation.customer_id else conversation.customer_id
    partner_result = await db.exec(select(User).where(User.id == partner_id))
    partner = partner_result.first()
    
    msg_result = await db.exec(select(DirectMessage).where(DirectMessage.conversation_id == conversation_id).order_by(DirectMessage.timestamp.asc()))
    past_messages = msg_result.all()
    
    return templates.TemplateResponse(request=request, name="chat.html", context={
        "request": request,
        "current_user": current_user,
        "conversation": conversation,
        "partner": partner,
        "past_messages": past_messages
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
