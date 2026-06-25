from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from pydantic import BaseModel
from typing import Any, List, Dict, Optional

from app.api.dependencies import get_db, get_current_user
from app.models.all_models import Job, User, Dispute, Conversation, DirectMessage
from app.services.gemini_service import analyze_dispute, estimate_job_price

router = APIRouter()


class DisputeAnalysisRequest(BaseModel):
    job_id: int
    dispute_reason: str
    photo_descriptions: Optional[List[str]] = None


class PriceEstimateRequest(BaseModel):
    description: str
    profession: str
    location: Optional[Dict[str, str]] = None
    photo_descriptions: Optional[List[str]] = None


@router.post("/dispute/analyze")
async def ai_dispute_analysis(
    request: DisputeAnalysisRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """AI-powered dispute analysis. Reads chat history and recommends refund split."""
    # Get the job
    job = await db.get(Job, request.job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    # Verify user is part of this job
    if current_user.id not in [job.customer_id, job.assigned_contractor_id]:
        raise HTTPException(status_code=403, detail="Not authorized for this job")

    # Get chat history from conversation
    conversation_result = await db.exec(
        select(Conversation).where(Conversation.job_id == request.job_id)
    )
    conversation = conversation_result.first()

    chat_history = []
    if conversation:
        messages_result = await db.exec(
            select(DirectMessage)
            .where(DirectMessage.conversation_id == conversation.id)
            .order_by(DirectMessage.created_at)
        )
        messages = list(messages_result.all())
        chat_history = [
            {"role": "customer" if msg.sender_id == job.customer_id else "contractor", "content": msg.content}
            for msg in messages
        ]

    # Get escrow amount
    from app.models.all_models import Escrow
    escrow_result = await db.exec(select(Escrow).where(Escrow.job_id == request.job_id))
    escrow = escrow_result.first()
    total_amount = str(escrow.total_amount) if escrow else "unknown"

    # Run AI analysis
    result = await analyze_dispute(
        chat_history=chat_history,
        dispute_reason=request.dispute_reason,
        job_description=job.description or "",
        total_amount=total_amount,
        photo_descriptions=request.photo_descriptions,
    )

    return {
        "job_id": request.job_id,
        "analysis": result["analysis"],
        "usage": result["metadata"],
    }


@router.post("/estimate")
async def ai_price_estimate(
    request: PriceEstimateRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """AI-powered price estimate for a job based on description, profession, and location."""
    result = await estimate_job_price(
        description=request.description,
        profession=request.profession,
        location=request.location,
        photo_descriptions=request.photo_descriptions,
    )

    return {
        "estimate": result["estimate"],
        "usage": result["metadata"],
    }
