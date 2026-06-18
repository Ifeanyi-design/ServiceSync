from fastapi import APIRouter, Request, Depends, HTTPException, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from sqlalchemy.orm import selectinload
from typing import Optional

from app.api.dependencies import get_current_user_optional, get_current_user, get_db
from app.models.all_models import User, Job, Conversation, DirectMessage, OmnichannelIntegration
from app.core.config import settings
from pathlib import Path

try:
    from app.models.audit_log import AIOperationsAuditLog
except ImportError:
    AIOperationsAuditLog = None

BASE_DIR = Path(__file__).resolve().parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

router = APIRouter()

def format_location(user: Optional[User]) -> str:
    if not user:
        return "—"
    parts = [part for part in [user.area, user.city, user.state_or_province, user.country] if part]
    if parts:
        return ", ".join(parts)
    return user.zip_code or user.postal_code or "—"

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

@router.get("/integrations", response_class=HTMLResponse)
async def integrations_page(request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "contractor":
        return RedirectResponse(url="/")
        
    result = await db.exec(select(OmnichannelIntegration).where(OmnichannelIntegration.contractor_id == current_user.id))
    integrations = result.all()
    
    return templates.TemplateResponse(request=request, name="integrations.html", context={
        "request": request,
        "current_user": current_user,
        "integrations": integrations
    })

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
    
    return templates.TemplateResponse(request=request, name="admin_dashboard.html", context={
        "request": request,
        "current_user": current_user,
        "audit_logs": audit_logs,
        "total_matches": total_matches,
        "total_reroutes": total_reroutes,
        "total_omnichannel_replies": total_omnichannel_replies,
        "avg_latency_ms": avg_latency_ms
    })

@router.get("/dashboard/customer", response_class=HTMLResponse)
async def customer_dashboard(request: Request, current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    if current_user.role != "customer":
        return RedirectResponse(url="/")
        
    result = await db.exec(select(Job).options(selectinload(Job.assigned_contractor)).where(Job.customer_id == current_user.id).order_by(Job.created_at.desc()))
    customer_jobs = result.all()
    
    return templates.TemplateResponse(request=request, name="customer_dashboard.html", context={
        "request": request,
        "current_user": current_user,
        "customer_jobs": customer_jobs,
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
    
    return templates.TemplateResponse(request=request, name="contractor_dashboard.html", context={
        "request": request,
        "current_user": current_user,
        "active_dispatches": active_dispatches,
        "jobs_today": jobs_today,
        "format_location": format_location
    })

@router.get("/chat", response_class=HTMLResponse)
async def chat_landing(current_user: User = Depends(get_current_user)):
    if current_user.role == "customer":
        return RedirectResponse(url="/dashboard/customer")
    if current_user.role == "contractor":
        return RedirectResponse(url="/dashboard/contractor")
    return RedirectResponse(url="/")

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
