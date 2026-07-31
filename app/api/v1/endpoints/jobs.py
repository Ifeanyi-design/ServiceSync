from fastapi import APIRouter, Depends, HTTPException, status, Form
from fastapi.responses import RedirectResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import Any
from datetime import datetime
from decimal import Decimal
from pydantic import BaseModel

from app.api.dependencies import get_db, get_current_user
from app.models.all_models import Job, User, Conversation, Escrow, Review
from app.models.audit_log import AIOperationsAuditLog
from app.schemas.job import JobResponse, BookJobRequest
from app.services.matching_engine import find_matches
from app.services.escrow_service import create_escrow, calculate_fees, refund_escrow
from app.services.alert_service import alert_new_booking

router = APIRouter()

@router.post("/{job_id}/book", response_model=JobResponse)
async def book_job(
    job_id: int,
    request: BookJobRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Customer confirms selection of a contractor.
    Creates a Conversation between the customer and contractor.
    """
    if current_user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can book jobs")

    # Fetch job
    job = await db.get(Job, job_id)
    if not job or job.customer_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    if job.status != "open":
        raise HTTPException(status_code=400, detail="Job is not open for booking")

    # Update job
    job.assigned_contractor_id = request.contractor_id
    job.status = "booked"
    db.add(job)

    # Ensure job has an id before conversation
    await db.flush()
    
    # Create Conversation channel (id = job.id so /chat/{job_id} works)
    conversation = Conversation(
        id=job.id,
        job_id=job.id,
        customer_id=current_user.id,
        contractor_id=request.contractor_id
    )
    db.add(conversation)
    
    # Create Escrow (unfunded until the customer pays)
    contractor = await db.get(User, request.contractor_id)
    amount = Decimal(str(contractor.base_pricing or 50.00)) if contractor else Decimal("50.00")
    escrow = await create_escrow(db, job, current_user, contractor or current_user, amount)
    
    await db.commit()
    await db.refresh(job)
    await db.refresh(conversation)

    # Dispatch cross-platform alert to contractor
    try:
        await alert_new_booking(db, contractor, job, current_user)
    except Exception:
        pass

    return job

@router.get("/auto-book")
async def auto_book_contractor(
    contractor_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Auto-book endpoint for seamless contractor selection from search page.
    Creates a job, conversation and escrow, then redirects straight to the
    escrow payment screen so the customer can fund the new job immediately
    (instead of landing back on a previous completed conversation).
    """
    if current_user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can book jobs")
    
    contractor = await db.get(User, contractor_id)
    if not contractor or contractor.role != "contractor":
        raise HTTPException(status_code=404, detail="Contractor not found")
    
    if contractor_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot book yourself")
    
    new_job = Job(
        customer_id=current_user.id,
        assigned_contractor_id=contractor_id,
        description=f"AI Triage Match - {contractor.profession or 'service'}",
        status="booked"
    )
    db.add(new_job)
    
    await db.flush()
    
    conversation = Conversation(
        id=new_job.id,
        job_id=new_job.id,
        customer_id=current_user.id,
        contractor_id=contractor_id
    )
    db.add(conversation)
    
    # Create Escrow
    amount = Decimal(str(contractor.base_pricing or 50.00))
    escrow = await create_escrow(db, new_job, current_user, contractor, amount)
    
    await db.commit()
    await db.refresh(new_job)

    # Dispatch cross-platform alert to contractor
    try:
        await alert_new_booking(db, contractor, new_job, current_user)
    except Exception:
        pass

    return RedirectResponse(url=f"/jobs/{new_job.id}/pay", status_code=303)

@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Contractor cancels an active job.
      - booked:               triggers Autonomous Recovery (reroute to next best pro)
      - in_progress / completed_pending: hard-cancels and refunds the customer if escrow is held
    """
    if current_user.role != "contractor":
        raise HTTPException(status_code=403, detail="Only contractors can use the cancel route")

    job = await db.get(Job, job_id)
    if not job or job.assigned_contractor_id != current_user.id:
        raise HTTPException(status_code=404, detail="Assigned job not found")

    if job.status == "booked":
        # Unassign the contractor (Autonomous Recovery)
        old_contractor_id = job.assigned_contractor_id
        job.assigned_contractor_id = None
        job.status = "open"
        db.add(job)
        await db.commit()
        await db.refresh(job)

        # Trigger Autonomous Recovery
        prof = "plumber"  # Default fallback
        old_contractor = await db.get(User, old_contractor_id)
        if old_contractor and old_contractor.profession:
            prof = old_contractor.profession

        customer = await db.get(User, job.customer_id)
        location = {
            "zip_code": customer.zip_code if customer else None,
            "country": customer.country if customer else None,
            "state_or_province": customer.state_or_province if customer else None,
            "city": customer.city if customer else None,
            "area": customer.area if customer else None,
            "postal_code": customer.postal_code if customer else None,
            "latitude": customer.latitude if customer else None,
            "longitude": customer.longitude if customer else None,
        }

        matches = await find_matches(db, prof, location)
        matched_contractors = matches["matched"]

        new_assigned_id = None
        for c in matched_contractors:
            if c["contractor_id"] != old_contractor_id:
                new_assigned_id = c["contractor_id"]
                break

        structured_decision = {
            "reason": "Contractor canceled",
            "previous_contractor": old_contractor_id,
            "new_assigned_contractor": new_assigned_id,
            "matches_found": len(matched_contractors),
        }

        if new_assigned_id:
            job.assigned_contractor_id = new_assigned_id
            job.status = "booked"
            db.add(job)
            await db.flush()

            new_conv = Conversation(
                id=job.id,
                job_id=job.id,
                customer_id=job.customer_id,
                contractor_id=new_assigned_id,
            )
            db.add(new_conv)
            structured_decision["status"] = "reroute_successful"
        else:
            structured_decision["status"] = "reroute_failed_no_matches"

        audit_log = AIOperationsAuditLog(
            action_type="auto_reroute",
            job_id=job.id,
            user_id=old_contractor_id,
            gemini_model_version="system_logic",
            raw_ai_response="Autonomous recovery triggered via cancel route.",
            structured_decision=structured_decision,
            status="success" if new_assigned_id else "fallback_triggered",
        )
        db.add(audit_log)

        await db.commit()
        await db.refresh(job)
        return job

    if job.status in ("in_progress", "completed_pending"):
        # Hard cancel + refund the customer if the escrow was funded
        result = await db.exec(select(Escrow).where(Escrow.job_id == job_id))
        escrow = result.first()
        if escrow and escrow.status == "held":
            try:
                await refund_escrow(db, escrow, reason="contractor_cancelled")
            except ValueError:
                pass
        job.status = "cancelled"
        db.add(job)
        await db.commit()
        await db.refresh(job)
        return job

    raise HTTPException(status_code=400, detail="This job can no longer be cancelled")

class ReviewCreate(BaseModel):
    rating: int
    comment: str

@router.post("/{job_id}/review")
async def create_job_review(
    job_id: int,
    payload: ReviewCreate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    job = await db.get(Job, job_id)
    if not job or job.customer_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "completed":
        raise HTTPException(status_code=400, detail="Job not completed")
    
    # Check if review already exists
    existing = await db.exec(select(Review).where(Review.job_id == job_id))
    if existing.first():
        raise HTTPException(status_code=400, detail="Review already submitted")
        
    review = Review(
        job_id=job_id,
        contractor_id=job.assigned_contractor_id,
        rating=payload.rating,
        comment=payload.comment
    )
    db.add(review)
    
    # Update contractor's reputation score (simple average approximation)
    contractor = await db.get(User, job.assigned_contractor_id)
    if contractor:
        old_score = contractor.reputation_score or 5.0
        contractor.reputation_score = round((old_score * 4 + payload.rating) / 5, 1)
        db.add(contractor)
        
    await db.commit()
    return {"ok": True}

@router.post("/{job_id}/action", response_model=JobResponse)
async def job_action(
    job_id: int,
    action: str = Form(...),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Two-sided job lifecycle actions:
      - contractor: start, mark_complete
      - customer:   confirm, dispute, cancel
    """
    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    now = datetime.utcnow()
    if action == "start":
        if current_user.role != "contractor" or job.assigned_contractor_id != current_user.id:
            raise HTTPException(status_code=403, detail="Only the assigned contractor can start the job")
        if job.status != "booked":
            raise HTTPException(status_code=400, detail="Job must be booked to start")
        job.status = "in_progress"
        job.started_at = now

    elif action == "mark_complete":
        if current_user.role != "contractor" or job.assigned_contractor_id != current_user.id:
            raise HTTPException(status_code=403, detail="Only the assigned contractor can mark complete")
        if job.status != "in_progress":
            raise HTTPException(status_code=400, detail="Job must be in progress to mark complete")
        job.status = "completed_pending"
        job.completed_at = now

    elif action == "confirm":
        if current_user.role != "customer" or job.customer_id != current_user.id:
            raise HTTPException(status_code=403, detail="Only the customer can confirm")
        if job.status != "completed_pending":
            raise HTTPException(status_code=400, detail="Job is not awaiting confirmation")
        job.status = "completed"
        # Release escrow + credit contractor wallet
        from app.services.escrow_service import release_escrow
        result = await db.exec(select(Escrow).where(Escrow.job_id == job_id))
        escrow = result.first()
        if escrow:
            await release_escrow(db, escrow)

    else:
        raise HTTPException(status_code=400, detail="Unknown action")

    db.add(job)
    try:
        from app.services.job_action_service import log_job_action
        await log_job_action(db, job_id, current_user.id, action)
    except Exception:
        pass
    await db.commit()
    await db.refresh(job)
    return job
