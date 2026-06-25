from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from decimal import Decimal
from typing import Any

from app.api.dependencies import get_db, get_current_user
from app.models.all_models import Job, User, Escrow, Dispute
from app.services.escrow_service import (
    create_escrow, release_escrow, refund_escrow,
    penalty_split_escrow, open_dispute, resolve_dispute,
)
from app.services.alert_service import alert_dispute_opened, alert_escrow_released

router = APIRouter()


@router.post("/{job_id}/fund")
async def fund_escrow(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Customer funds escrow for a booked job."""
    if current_user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can fund escrow")

    job = await db.get(Job, job_id)
    if not job or job.customer_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.status != "booked":
        raise HTTPException(status_code=400, detail="Job must be booked before funding escrow")

    # Check if escrow already exists
    existing = await db.exec(select(Escrow).where(Escrow.job_id == job_id))
    if existing.first():
        raise HTTPException(status_code=400, detail="Escrow already exists for this job")

    contractor = await db.get(User, job.assigned_contractor_id)
    if not contractor:
        raise HTTPException(status_code=400, detail="No contractor assigned")

    # Use contractor's base pricing as the amount
    amount = Decimal(str(contractor.base_pricing or 50.00))

    escrow = await create_escrow(db, job, current_user, contractor, amount)
    await db.commit()
    await db.refresh(escrow)

    return {
        "escrow_id": escrow.id,
        "status": escrow.status,
        "total_amount": str(escrow.total_amount),
        "platform_fee": str(escrow.platform_fee),
        "contractor_payout": str(escrow.contractor_payout),
        "currency": escrow.currency,
    }


@router.post("/{job_id}/release")
async def release_funds(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Release escrow funds to contractor on job completion."""
    if current_user.role not in ("customer", "admin"):
        raise HTTPException(status_code=403, detail="Not authorized")

    result = await db.exec(select(Escrow).where(Escrow.job_id == job_id))
    escrow = result.first()
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")

    if current_user.role == "customer" and escrow.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your escrow")

    try:
        escrow = await release_escrow(db, escrow)
        
        # Update job status
        job = await db.get(Job, job_id)
        if job:
            job.status = "completed"
            db.add(job)
        
        await db.commit()
        await db.refresh(escrow)

        # Alert contractor about payment release
        try:
            contractor = await db.get(User, escrow.contractor_id)
            if contractor:
                await alert_escrow_released(db, contractor, job_id, str(escrow.contractor_payout))
        except Exception:
            pass
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "escrow_id": escrow.id,
        "status": escrow.status,
        "contractor_payout": str(escrow.contractor_payout),
        "payout_reference": escrow.payout_reference_id,
    }


@router.post("/{job_id}/cancel")
async def cancel_escrow(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Full refund to customer (contractor cancellation/no-show)."""
    result = await db.exec(select(Escrow).where(Escrow.job_id == job_id))
    escrow = result.first()
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")

    try:
        escrow = await refund_escrow(db, escrow, reason="contractor_cancelled")
        await db.commit()
        await db.refresh(escrow)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "escrow_id": escrow.id,
        "status": escrow.status,
        "customer_refund": str(escrow.customer_refund),
    }


@router.post("/{job_id}/late-cancel")
async def late_cancel_escrow(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Late customer cancellation — penalty split."""
    if current_user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can cancel")

    result = await db.exec(select(Escrow).where(Escrow.job_id == job_id))
    escrow = result.first()
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    if escrow.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your escrow")

    try:
        escrow = await penalty_split_escrow(db, escrow)
        await db.commit()
        await db.refresh(escrow)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "escrow_id": escrow.id,
        "status": escrow.status,
        "contractor_payout": str(escrow.contractor_payout),
        "customer_refund": str(escrow.customer_refund),
    }


@router.post("/{job_id}/dispute")
async def dispute_escrow(
    job_id: int,
    reason: str,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Customer opens a dispute on an escrowed job."""
    if current_user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can open disputes")

    result = await db.exec(select(Escrow).where(Escrow.job_id == job_id))
    escrow = result.first()
    if not escrow:
        raise HTTPException(status_code=404, detail="Escrow not found")
    if escrow.customer_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not your escrow")

    try:
        dispute = await open_dispute(db, escrow, current_user, reason)
        await db.commit()
        await db.refresh(dispute)

        # Alert contractor about dispute
        try:
            contractor = await db.get(User, escrow.contractor_id)
            if contractor:
                await alert_dispute_opened(db, contractor, job_id, reason)
        except Exception:
            pass
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "dispute_id": dispute.id,
        "escrow_status": escrow.status,
        "dispute_status": dispute.status,
    }


@router.post("/{job_id}/resolve")
async def resolve_escrow_dispute(
    job_id: int,
    resolution: str,
    refund_pct: float,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Admin resolves a dispute."""
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Only admins can resolve disputes")

    # Find dispute for this job
    dispute_result = await db.exec(select(Dispute).where(Dispute.job_id == job_id))
    dispute = dispute_result.first()
    if not dispute:
        raise HTTPException(status_code=404, detail="No dispute found for this job")

    if dispute.status == "resolved":
        raise HTTPException(status_code=400, detail="Dispute already resolved")

    try:
        dispute = await resolve_dispute(db, dispute, resolution, refund_pct, current_user.id)
        await db.commit()
        await db.refresh(dispute)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {
        "dispute_id": dispute.id,
        "status": dispute.status,
        "refund_pct": dispute.ai_recommended_refund_pct,
    }


@router.get("/{job_id}/status")
async def get_escrow_status(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Get escrow status for a job."""
    result = await db.exec(select(Escrow).where(Escrow.job_id == job_id))
    escrow = result.first()
    if not escrow:
        return {"exists": False}

    return {
        "exists": True,
        "escrow_id": escrow.id,
        "status": escrow.status,
        "total_amount": str(escrow.total_amount),
        "platform_fee": str(escrow.platform_fee),
        "contractor_payout": str(escrow.contractor_payout),
        "customer_refund": str(escrow.customer_refund),
        "currency": escrow.currency,
        "funded_at": escrow.funded_at.isoformat() if escrow.funded_at else None,
        "released_at": escrow.released_at.isoformat() if escrow.released_at else None,
    }
