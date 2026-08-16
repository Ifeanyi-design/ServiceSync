"""ServiceSync Voice — HTTP endpoints.

POST /api/v1/voice/dispatchexternal
    Trigger CALL-E calls to available contractors for a job and store the
    in-flight offers. Customer-only.

GET  /api/v1/voice/dispatchexternal/{job_id}
    Poll CALL-E for completed calls, resolve structured results, and return the
    ranked offers + the best contractor. Customer-only.
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import Optional, List

from app.api.dependencies import get_db, get_current_user
from app.models.all_models import Job, User
from app.services.voice_dispatch import (
    DISPATCH_STATE,
    apply_webhook_event,
    best_offer,
    dispatch_calls,
    resolve_offer,
    ProviderOffer,
)

router = APIRouter()


def _offer_out(o: ProviderOffer) -> dict:
    d = asdict(o)
    d["result"] = o.result.model_dump()
    return d


@router.post("/dispatch", response_model=dict)
async def dispatch(
    job_id: int,
    max_candidates: int = 5,
    contractor_ids: Optional[List[int]] = Query(None, description="Restrict calls to these contractor IDs (e.g. CCTV-matched installers)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    job = await db.get(Job, job_id)
    if not job or job.customer_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    # Phase 2: prefer explicitly supplied IDs, then job.matched_contractor_ids
    # (CCTV intake match list), then fall back to a global available pool.
    if contractor_ids:
        rows = [await db.get(User, cid) for cid in contractor_ids]
        contractors = [c for c in rows if c and c.role == "contractor" and c.id != current_user.id]
    elif job.matched_contractor_ids:
        rows = [await db.get(User, cid) for cid in job.matched_contractor_ids]
        contractors = [c for c in rows if c and c.role == "contractor" and c.id != current_user.id][:max_candidates]
    else:
        result = await db.exec(
            select(User)
            .where(User.role == "contractor")
            .where(User.availability_status == "Available")
            .limit(max_candidates * 3)
        )
        contractors = [c for c in result.all() if c.id != current_user.id][:max_candidates]

    if not contractors:
        raise HTTPException(status_code=400, detail="No contractors to call")

    offers = await dispatch_calls(job, contractors)
    DISPATCH_STATE[job_id] = offers
    return {"job_id": job_id, "dispatched": len(offers), "offers": [_offer_out(o) for o in offers]}


@router.get("/dispatch/{job_id}", response_model=dict)
async def poll(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    job = await db.get(Job, job_id)
    if not job or job.customer_id != current_user.id:
        raise HTTPException(status_code=404, detail="Job not found")

    offers = DISPATCH_STATE.get(job_id)
    if offers is None:
        raise HTTPException(status_code=404, detail="No dispatch for this job")

    resolved = []
    for o in offers:
        if o.call_id and not o.raw_transcript and not o.error:
            o = await resolve_offer(job, o)
        resolved.append(o)
    DISPATCH_STATE[job_id] = resolved

    best = best_offer(resolved)
    return {
        "job_id": job_id,
        "offers": [_offer_out(o) for o in resolved],
        "best_contractor_id": best.contractor_id if best else None,
    }
