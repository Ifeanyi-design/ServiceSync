from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import RedirectResponse
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import Any
from decimal import Decimal

from app.api.dependencies import get_db, get_current_user
from app.models.all_models import Job, User, Conversation, Escrow
from app.models.audit_log import AIOperationsAuditLog
from app.schemas.job import JobResponse, BookJobRequest
from app.services.matching_engine import find_matches
from app.services.escrow_service import create_escrow, calculate_fees
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
    
    # Create Escrow
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
    Creates a job and conversation, then redirects to chat.
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

    return RedirectResponse(url=f"/chat/{new_job.id}", status_code=303)

@router.post("/{job_id}/cancel", response_model=JobResponse)
async def cancel_job(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Contractor cancels an active job. 
    Triggers Autonomous Recovery Logic to find the next best contractor.
    """
    if current_user.role != "contractor":
        raise HTTPException(status_code=403, detail="Only contractors can use the cancel route")

    job = await db.get(Job, job_id)
    if not job or job.assigned_contractor_id != current_user.id:
        raise HTTPException(status_code=404, detail="Assigned job not found")

    if job.status != "booked":
        raise HTTPException(status_code=400, detail="Job is not booked")

    # Unassign the contractor
    old_contractor_id = job.assigned_contractor_id
    job.assigned_contractor_id = None
    job.status = "open"
    db.add(job)
    await db.commit()
    await db.refresh(job)

    # Trigger Autonomous Recovery
    prof = "plumber" # Default fallback
    old_contractor = await db.get(User, old_contractor_id)
    if old_contractor and old_contractor.profession:
        prof = old_contractor.profession

    # Fetch location from customer
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
    # Filter out the old contractor
    for c in matched_contractors:
        if c["contractor_id"] != old_contractor_id:
            new_assigned_id = c["contractor_id"]
            break
            
    structured_decision = {
        "reason": "Contractor canceled",
        "previous_contractor": old_contractor_id,
        "new_assigned_contractor": new_assigned_id,
        "matches_found": len(matched_contractors)
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
            contractor_id=new_assigned_id
        )
        db.add(new_conv)
        structured_decision["status"] = "reroute_successful"
    else:
        structured_decision["status"] = "reroute_failed_no_matches"

    # Log to AIOperationsAuditLog
    audit_log = AIOperationsAuditLog(
        action_type="auto_reroute",
        job_id=job.id,
        user_id=old_contractor_id,
        gemini_model_version="system_logic",
        raw_ai_response="Autonomous recovery triggered via cancel route.",
        structured_decision=structured_decision,
        status="success" if new_assigned_id else "fallback_triggered"
    )
    db.add(audit_log)
    
    await db.commit()
    await db.refresh(job)
    
    return job
