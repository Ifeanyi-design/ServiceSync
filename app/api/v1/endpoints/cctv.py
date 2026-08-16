"""Phase 1 — CCTV vertical endpoints.

Customer: POST /api/v1/cctv/intake  → AI brief + matched CCTV contractors + job.
Contractor: POST /api/v1/cctv/{job_id}/draft-quote → AI proposal from the brief.

The created job (status "open", category "cctv", brief set) drops straight into
the existing booking → escrow → pay → complete flow.
"""
from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.api.dependencies import get_db, get_current_user
from app.models.all_models import User, Job
from app.services.intake_service import intake_job
from app.services.quote_service import draft_quote

router = APIRouter()


class IntakeRequest(BaseModel):
    description: str
    category: str = "cctv"
    city: Optional[str] = None
    country: Optional[str] = None


def _matches_category(user: User, category: str) -> bool:
    cat = category.lower()
    specs = [s.lower() for s in (user.specialties or [])]
    prof = (user.profession or "").lower()
    if cat in specs or cat in prof:
        return True
    return any(k in prof for k in ("cctv", "camera", "security", "surveil"))


async def find_category_contractors(
    db: AsyncSession, category: str, city: Optional[str] = None, country: Optional[str] = None
) -> list[dict]:
    result = await db.exec(select(User).where(User.role == "contractor"))
    out = []
    for u in result.all():
        if not _matches_category(u, category):
            continue
        if city and (u.city or "").lower() != city.lower():
            continue
        if country and (u.country or "").lower() != country.lower():
            continue
        out.append({
            "id": u.id,
            "full_name": u.full_name,
            "profession": u.profession,
            "city": u.city,
            "country": u.country,
            "reputation_score": u.reputation_score,
            "availability_status": u.availability_status,
            "specialties": u.specialties,
        })
    # Best first: available, then by reputation.
    out.sort(key=lambda c: (c["availability_status"] != "Available", -(c["reputation_score"] or 0)))
    return out


@router.post("/intake", response_model=dict)
async def cctv_intake(
    req: IntakeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if current_user.role != "customer":
        raise HTTPException(status_code=403, detail="Only customers can create jobs")

    brief = await intake_job(req.description, req.category)
    job = Job(
        customer_id=current_user.id,
        description=req.description,
        category=req.category,
        brief=brief.model_dump(),
        status="open",
        city=req.city,
        country=req.country,
    )
    db.add(job)
    await db.flush()

    contractors = await find_category_contractors(db, req.category, req.city, req.country)
    job.matched_contractor_ids = [c["id"] for c in contractors]
    return {
        "job_id": job.id,
        "brief": brief.model_dump(),
        "contractors": contractors[:10],
    }


@router.post("/{job_id}/draft-quote", response_model=dict)
async def draft_quote_endpoint(
    job_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> dict:
    if current_user.role != "contractor":
        raise HTTPException(status_code=403, detail="Only contractors can draft quotes")

    job = await db.get(Job, job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    quote = await draft_quote(job.brief or {}, current_user, category=job.category or "cctv")
    return quote.model_dump()
