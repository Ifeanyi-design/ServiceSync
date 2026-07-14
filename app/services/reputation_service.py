"""
Reputation scoring service.

Computes a composite 0-100 reputation score for a contractor from real
marketplace signals: average review rating, job completion rate, dispute
rate, and repeat-customer rate.

The score is intentionally computed only from data that exists in the
database. If a contractor has no completed jobs and no reviews, the score
stays ``None`` (we never fabricate a reputation).
"""
from typing import Optional, Dict, Any

from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.all_models import User, Job, Review, Dispute


# Component weights (must sum to 1.0 when all components are present).
_WEIGHT_RATING = 0.50
_WEIGHT_COMPLETION = 0.25
_WEIGHT_DISPUTE = 0.15
_WEIGHT_REPEAT = 0.10

# Verification tier auto-upgrade thresholds (only used to *suggest*, never to
# override an admin decision — see recalculate_reputation()).
_TERMINAL_STATUSES = ("completed", "cancelled")


async def compute_reputation_metrics(db: AsyncSession, contractor_id: int) -> Dict[str, Any]:
    """Return the raw reputation metrics and composite score for a contractor.

    Returns a dict with:
      - average_rating (float | None)
      - review_count (int)
      - completed_jobs (int)
      - cancelled_jobs (int)
      - completion_rate (float 0-1 | None)
      - dispute_count (int)
      - dispute_rate (float 0-1 | None)
      - repeat_customer_rate (float 0-1 | None)
      - score (float 0-100 | None)
    """
    # --- Reviews ---
    reviews_result = await db.exec(
        select(Review).where(Review.contractor_id == contractor_id)
    )
    reviews = list(reviews_result.all())
    review_count = len(reviews)
    average_rating: Optional[float] = (
        round(sum(r.rating for r in reviews) / review_count, 2) if review_count else None
    )

    # --- Jobs assigned to this contractor ---
    jobs_result = await db.exec(
        select(Job).where(Job.assigned_contractor_id == contractor_id)
    )
    jobs = list(jobs_result.all())
    completed_jobs = [j for j in jobs if j.status == "completed"]
    cancelled_jobs = [j for j in jobs if j.status == "cancelled"]
    terminal_jobs = [j for j in jobs if j.status in _TERMINAL_STATUSES]

    completion_rate: Optional[float] = (
        len(completed_jobs) / len(terminal_jobs) if terminal_jobs else None
    )

    # --- Disputes on this contractor's jobs ---
    dispute_count = 0
    if completed_jobs or terminal_jobs:
        job_ids = [j.id for j in jobs if j.id is not None]
        if job_ids:
            disputes_result = await db.exec(
                select(Dispute).where(Dispute.job_id.in_(job_ids))
            )
            dispute_count = len(list(disputes_result.all()))
    dispute_rate: Optional[float] = (
        dispute_count / len(completed_jobs) if completed_jobs else None
    )

    # --- Repeat customer rate ---
    repeat_customer_rate: Optional[float] = None
    if completed_jobs:
        customer_ids = [j.customer_id for j in completed_jobs]
        distinct = set(customer_ids)
        if distinct:
            repeat = sum(1 for c in distinct if customer_ids.count(c) > 1)
            repeat_customer_rate = repeat / len(distinct)

    score = _composite_score(
        average_rating=average_rating,
        completion_rate=completion_rate,
        dispute_rate=dispute_rate,
        repeat_customer_rate=repeat_customer_rate,
    )

    return {
        "average_rating": average_rating,
        "review_count": review_count,
        "completed_jobs": len(completed_jobs),
        "cancelled_jobs": len(cancelled_jobs),
        "completion_rate": completion_rate,
        "dispute_count": dispute_count,
        "dispute_rate": dispute_rate,
        "repeat_customer_rate": repeat_customer_rate,
        "score": score,
    }


def _composite_score(
    average_rating: Optional[float],
    completion_rate: Optional[float],
    dispute_rate: Optional[float],
    repeat_customer_rate: Optional[float],
) -> Optional[float]:
    """Blend available components into a 0-100 score, re-normalizing weights
    over whichever components have data. Returns None if nothing is available."""
    parts = []  # (weight, value_0_to_100)

    if average_rating is not None:
        parts.append((_WEIGHT_RATING, (average_rating / 5.0) * 100.0))
    if completion_rate is not None:
        parts.append((_WEIGHT_COMPLETION, completion_rate * 100.0))
    if dispute_rate is not None:
        parts.append((_WEIGHT_DISPUTE, (1.0 - min(dispute_rate, 1.0)) * 100.0))
    if repeat_customer_rate is not None:
        parts.append((_WEIGHT_REPEAT, repeat_customer_rate * 100.0))

    if not parts:
        return None

    total_weight = sum(w for w, _ in parts)
    if total_weight <= 0:
        return None

    weighted = sum(w * v for w, v in parts) / total_weight
    return round(weighted, 1)


async def recalculate_reputation(db: AsyncSession, contractor_id: int) -> Optional[float]:
    """Recompute and persist a contractor's reputation score.

    Uses ``db.flush()`` so it composes inside an existing transaction; the
    caller is responsible for committing.
    Returns the new score (or None if not enough data).
    """
    contractor = await db.get(User, contractor_id)
    if not contractor or contractor.role != "contractor":
        return None

    metrics = await compute_reputation_metrics(db, contractor_id)
    score = metrics["score"]

    if score is not None:
        contractor.reputation_score = score
        db.add(contractor)
        await db.flush()

    return score
