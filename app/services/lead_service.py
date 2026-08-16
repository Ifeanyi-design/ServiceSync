"""Phase 6 — lead routing (free-tool estimate -> matched contractors).

Given a job lead, find contractors whose primary trade or specialties match the
job category, record the match on the job, and notify them (in-app via the
derived notification feed + an email stub). No LLM/network required.
"""
from __future__ import annotations

from typing import List

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.all_models import Job, User
from app.services.email_service import send_email


async def match_contractors_for_job(db: AsyncSession, job: Job) -> List[User]:
    """Return contractors whose trade/specialties match the job category."""
    cat = (job.category or "general").lower()
    result = await db.exec(select(User).where(User.role == "contractor"))
    matches: List[User] = []
    for u in result.all():
        prof = (u.profession or "").lower()
        specs = [s.lower() for s in (u.specialties or [])]
        if cat == "general" or prof == cat or cat in specs:
            matches.append(u)
    return matches


async def open_leads_for_contractor(db: AsyncSession, contractor: User) -> List[Job]:
    """Open, unassigned leads whose category matches this contractor's trade."""
    trades = {(contractor.profession or "").lower()} | {s.lower() for s in (contractor.specialties or [])}
    result = await db.exec(
        select(Job).where(
            Job.assigned_contractor_id == None,  # noqa: E711
            Job.status.in_(["open", "quoted", "requested"]),
        ).order_by(Job.created_at.desc())
    )
    leads: List[Job] = []
    for job in result.all():
        if job.customer_id == contractor.id:
            continue
        cat = (job.category or "general").lower()
        if cat != "general" and cat not in trades:
            continue
        leads.append(job)
    return leads


async def notify_matched_contractors_for_lead(db: AsyncSession, job: Job) -> List[int]:
    """Record matched contractors on the job and email them a lead alert."""
    matches = await match_contractors_for_job(db, job)
    ids = [u.id for u in matches]
    job.matched_contractor_ids = ids
    db.add(job)
    for u in matches:
        try:
            await send_email(
                u.email,
                "New ServiceSync job lead in your trade",
                f"<p>A new job lead matches your trade:</p>"
                f"<p><strong>{job.description}</strong></p>"
                f"<p>Open the app to view and respond to the lead.</p>",
                f"New job lead: {job.description}",
            )
        except Exception:
            # Email is best-effort (SMTP may be unconfigured in demo mode).
            pass
    return ids
