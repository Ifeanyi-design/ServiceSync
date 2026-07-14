"""
Subscription / monetization service (Phase 7).

Handles the Free vs Premium tiers, the 14-day premium trial, tier-based
commission rates, and (mock) upgrade / downgrade transitions. There is no
real billing integration yet — this is a deterministic, demo-ready layer that
the escrow, matching, and UI layers read from.
"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from app.core.config import settings
from app.models.all_models import User


def _now() -> datetime:
    return datetime.utcnow()


def is_trial_active(user: User) -> bool:
    """True if the user is on an unexpired premium trial."""
    return (
        user.subscription_status == "trialing"
        and user.trial_ends_at is not None
        and user.trial_ends_at > _now()
    )


def effective_tier(user: User) -> str:
    """The tier that should actually apply *right now*.

    A premium subscription counts while active; a trial counts while it has
    not expired. Everything else falls back to free.
    """
    if user is None:
        return "free"
    if user.subscription_tier == "premium" and user.subscription_status == "active":
        # An active paid subscription (optionally bounded by subscription_ends_at)
        if user.subscription_ends_at is None or user.subscription_ends_at > _now():
            return "premium"
        return "free"
    if is_trial_active(user):
        return "premium"
    return "free"


def is_premium(user: User) -> bool:
    return effective_tier(user) == "premium"


def trial_days_remaining(user: User) -> Optional[int]:
    if user.trial_ends_at is None or not is_trial_active(user):
        return None
    delta = user.trial_ends_at - _now()
    return max(0, delta.days + (1 if delta.seconds else 0))


def commission_rate(user: Optional[User]) -> Decimal:
    """Platform commission rate for this user's effective tier."""
    if user is not None and effective_tier(user) == "premium":
        return Decimal(str(settings.PLATFORM_FEE_PCT_PREMIUM))
    return Decimal(str(settings.PLATFORM_FEE_PCT_FREE))


def start_trial(user: User) -> User:
    """Put a brand-new contractor on the premium trial."""
    user.subscription_tier = "premium"
    user.subscription_status = "trialing"
    user.trial_ends_at = _now() + timedelta(days=settings.PREMIUM_TRIAL_DAYS)
    user.subscription_started_at = _now()
    user.subscription_ends_at = None
    return user


def upgrade_to_premium(user: User) -> User:
    """Activate a (mock) paid premium subscription for 30 days."""
    user.subscription_tier = "premium"
    user.subscription_status = "active"
    user.subscription_started_at = _now()
    user.subscription_ends_at = _now() + timedelta(days=30)
    user.trial_ends_at = None
    return user


def cancel_subscription(user: User) -> User:
    """Downgrade to the free tier."""
    user.subscription_tier = "free"
    user.subscription_status = "active"
    user.trial_ends_at = None
    user.subscription_ends_at = None
    return user


async def enforce_expiry(db: AsyncSession, user: User) -> User:
    """Lazily flip an expired trial / subscription down to free.

    Called on dashboard loads so tier state is always self-healing without a
    background job. Commits only if something changed.
    """
    if user is None or user.role != "contractor":
        return user

    changed = False
    if (
        user.subscription_status == "trialing"
        and user.trial_ends_at is not None
        and user.trial_ends_at <= _now()
    ):
        user.subscription_tier = "free"
        user.subscription_status = "expired"
        changed = True
    elif (
        user.subscription_tier == "premium"
        and user.subscription_status == "active"
        and user.subscription_ends_at is not None
        and user.subscription_ends_at <= _now()
    ):
        user.subscription_tier = "free"
        user.subscription_status = "expired"
        changed = True

    if changed:
        db.add(user)
        await db.commit()
        await db.refresh(user)
    return user
