"""
Contractor wallet service (Phase 9).

Manages a per-contractor wallet with a *pending* (clearing) balance and an
*available* balance. When an escrow is released, the contractor payout is
credited as pending and becomes available after a clearing window
(faster for premium contractors). Contractors can then withdraw available
funds — routed through Paystack Transfer (NG/Africa), Stripe Connect, or a
safe demo record depending on what is configured.
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


def _wallet_currency(wallet: Optional[ContractorWallet] = None) -> str:
    """The currency this wallet is accounted in."""
    if wallet and wallet.currency:
        return wallet.currency
    # Fall back to the platform's active charge currency.
    return settings.PAYSTACK_CURRENCY if settings.active_processor() == "paystack" \
        else settings.PAYMENT_CURRENCY


async def ensure_wallet(db: AsyncSession, contractor_id: int) -> ContractorWallet:
    result = await db.exec(
        select(ContractorWallet).where(ContractorWallet.contractor_id == contractor_id)
    )
    wallet = result.first()
    if wallet is None:
        wallet = ContractorWallet(
            contractor_id=contractor_id,
            currency=_wallet_currency(),
        )
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
    currency: Optional[str] = None,
) -> WalletTransaction:
    """Credit a released payout as pending, with an availability date."""
    wallet = await ensure_wallet(db, contractor_id)
    if currency:
        wallet.currency = currency
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
        currency=currency or wallet.currency,
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
    currency: Optional[str] = None,
    reference: Optional[str] = None,
    note: Optional[str] = None,
    method: str = "bank",
) -> WalletTransaction:
    """Withdraw from the available balance (funds must already be cleared).

    The payout is routed in the wallet's currency:
    1. Paystack Transfer when the contractor has a verified recipient code and
       Paystack is live (NG/Africa markets).
    2. Stripe Connect transfer when the contractor is connected and Stripe is
       configured.
    3. A safe demo record otherwise — the wallet is still debited so the
       full flow is testable with zero configuration.
    """
    wallet = await ensure_wallet(db, contractor_id)
    # Make sure any cleared funds are reflected first
    await clear_funds(db, contractor_id)
    cur = (currency or wallet.currency or settings.PAYMENT_CURRENCY).upper()
    wallet.currency = cur
    available = wallet.available_balance or Decimal("0.00")
    if amount <= 0:
        raise ValueError("Withdrawal amount must be greater than zero")
    if amount > available:
        raise ValueError(f"Insufficient available balance ({amount} {cur})")

    contractor = await db.get(User, contractor_id)

    from app.services.payment_gateway import (
        payout_to_contractor,
        payout_to_contractor_via_paystack,
    )

    recipient = getattr(contractor, "paystack_recipient_code", None) if contractor else None
    ref = reference or f"wd_{contractor_id}_{int(datetime.utcnow().timestamp())}"

    payout = None
    if recipient and settings.paystack_live and cur in ("NGN", "GHS", "KES", "ZAR", "USD"):
        kobo = int(round(float(amount) * 100))
        payout = payout_to_contractor_via_paystack(
            contractor_id, kobo, recipient, cur, reason="Wallet withdrawal",
        )
    else:
        connected = contractor.stripe_account_id if contractor else None
        payout = payout_to_contractor(
            contractor_id, amount, cur.lower(), connected,
            metadata={"kind": "withdrawal", "method": method},
        )

    if payout is not None and payout.get("success") is False:
        raise ValueError(payout.get("error", "Payout failed"))

    wallet.available_balance = available - amount
    db.add(wallet)

    txn = WalletTransaction(
        contractor_id=contractor_id,
        type="withdrawal",
        amount=amount,
        currency=cur,
        status="completed",
        reference=(payout or {}).get("reference_id") or ref,
        note=note,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return txn


async def get_wallet(db: AsyncSession, contractor_id: int) -> ContractorWallet:
    await clear_funds(db, contractor_id)
    wallet = await ensure_wallet(db, contractor_id)
    wallet.currency = _wallet_currency(wallet)
    return wallet


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
    cur = _wallet_currency(wallet)
    available = wallet.available_balance or Decimal("0.00")
    if amount <= 0:
        raise ValueError("Amount must be greater than zero")
    if amount > available:
        raise ValueError(f"Insufficient available balance ({amount} {cur})")

    wallet.available_balance = available - amount
    db.add(wallet)

    txn = WalletTransaction(
        contractor_id=contractor_id,
        type="subscription_payment",
        amount=amount,
        currency=cur,
        status="completed",
        reference=reference,
        note=note,
    )
    db.add(txn)
    await db.commit()
    await db.refresh(txn)
    return txn