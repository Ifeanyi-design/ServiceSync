"""
Contractor wallet service (Phase 9).

Manages a per-contractor wallet with a *pending* (clearing) balance and an
*available* balance. When an escrow is released, the contractor payout is
credited as pending and becomes available after a clearing window
(faster for premium contractors). Contractors can then withdraw available
funds (mock payout today; Stripe-ready later).
"""
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.core.config import settings
from app.models.all_models import ContractorWallet, WalletTransaction, User


def _now() -> datetime:
    return datetime.utcnow()


async def ensure_wallet(db: AsyncSession, contractor_id: int) -> ContractorWallet:
    result = await db.exec(
        select(ContractorWallet).where(ContractorWallet.contractor_id == contractor_id)
    )
    wallet = result.first()
    if wallet is None:
        wallet = ContractorWallet(contractor_id=contractor_id)
        db.add(wallet)
        await db.commit()
        await db.refresh(wallet)
    return wallet


async def credit_pending(
    db: AsyncSession,
    contractor_id: int,
    amount: Decimal,
    reference: str,
    note: Optional[str] = None,
) -> WalletTransaction:
    """Credit a released payout as pending, with an availability date."""
    wallet = await ensure_wallet(db, contractor_id)
    contractor = await db.get(User, contractor_id)
    clearing = settings.PREMIUM_CLEARING_DAYS if (
        contractor and contractor.subscription_tier == "premium"
        and contractor.subscription_status in ("active", "trialing")
    ) else settings.CLEARING_DAYS
    available_at = _now() + timedelta(days=clearing)

    wallet.pending_balance = (wallet.pending_balance or Decimal("0.00")) + amount
    db.add(wallet)

    txn = WalletTransaction(
        contractor_id=contractor_id,
        type="credit_pending",
        amount=amount,
        status="pending",
        reference=reference,
        note=note,
        available_at=available_at,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return txn


async def clear_funds(db: AsyncSession, contractor_id: int) -> Decimal:
    """Move any pending transactions whose clearing window has elapsed into available."""
    wallet = await ensure_wallet(db, contractor_id)
    result = await db.exec(
        select(WalletTransaction).where(
            WalletTransaction.contractor_id == contractor_id,
            WalletTransaction.type == "credit_pending",
            WalletTransaction.status == "pending",
        )
    )
    cleared = Decimal("0.00")
    now = _now()
    for txn in result.all():
        if txn.available_at and txn.available_at <= now:
            txn.status = "completed"
            db.add(txn)
            cleared += txn.amount
    if cleared > 0:
        wallet.pending_balance = (wallet.pending_balance or Decimal("0.00")) - cleared
        wallet.available_balance = (wallet.available_balance or Decimal("0.00")) + cleared
        db.add(wallet)
        await db.commit()
        await db.refresh(wallet)
    return cleared


async def withdraw(
    db: AsyncSession,
    contractor_id: int,
    amount: Decimal,
    reference: str,
    note: Optional[str] = None,
) -> WalletTransaction:
    """Withdraw from the available balance (funds must already be cleared)."""
    wallet = await ensure_wallet(db, contractor_id)
    # Make sure any cleared funds are reflected first
    await clear_funds(db, contractor_id)
    available = wallet.available_balance or Decimal("0.00")
    if amount <= 0:
        raise ValueError("Withdrawal amount must be greater than zero")
    if amount > available:
        raise ValueError(f"Insufficient available balance (${available})")

    wallet.available_balance = available - amount
    db.add(wallet)

    # Real payout to contractor's bank (Stripe Connect) when configured
    from app.services.payment_gateway import payout_to_contractor
    contractor = await db.get(User, contractor_id)
    connected = contractor.stripe_account_id if contractor else None
    payout = payout_to_contractor(contractor_id, amount, "usd", connected, metadata={"kind": "withdrawal"})

    txn = WalletTransaction(
        contractor_id=contractor_id,
        type="withdrawal",
        amount=amount,
        status="completed",
        reference=payout["reference_id"],
        note=note,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return txn


async def get_wallet(db: AsyncSession, contractor_id: int) -> ContractorWallet:
    await clear_funds(db, contractor_id)
    return await ensure_wallet(db, contractor_id)


async def pay_subscription_from_wallet(
    db: AsyncSession,
    contractor_id: int,
    amount: Decimal,
    reference: str,
    note: Optional[str] = None,
) -> WalletTransaction:
    """Pay for a subscription/boost using cleared wallet earnings (no bank payout)."""
    wallet = await ensure_wallet(db, contractor_id)
    await clear_funds(db, contractor_id)
    available = wallet.available_balance or Decimal("0.00")
    if amount <= 0:
        raise ValueError("Amount must be greater than zero")
    if amount > available:
        raise ValueError(f"Insufficient available balance (${available})")

    wallet.available_balance = available - amount
    db.add(wallet)

    txn = WalletTransaction(
        contractor_id=contractor_id,
        type="subscription_payment",
        amount=amount,
        status="completed",
        reference=reference,
        note=note,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return txn
