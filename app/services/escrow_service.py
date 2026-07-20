import asyncio
from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from typing import Optional
import json
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.models.all_models import Escrow, Dispute, Job, User, Receipt, DirectMessage, Conversation
from app.services.payout_gateway import process_payout, refund_payment
from app.services.payment_gateway import capture_payment
from app.services.subscription_service import commission_rate
from app.services.alert_service import dispatch_alert
from app.core.config import settings

# Default platform fee percentage (used when a tier-specific rate is unavailable)
PLATFORM_FEE_PCT = Decimal("0.10")  # 10%


def calculate_fees(amount: Decimal, rate: Decimal | None = None) -> dict:
    """Calculate platform fee and contractor payout from total amount.

    ``rate`` is the platform commission (e.g. Decimal('0.05') for 5%). When not
    provided the default PLATFORM_FEE_PCT applies.
    """
    fee_rate = rate if rate is not None else PLATFORM_FEE_PCT
    platform_fee = (amount * fee_rate).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    contractor_payout = amount - platform_fee
    return {
        "total_amount": amount,
        "platform_fee": platform_fee,
        "contractor_payout": contractor_payout,
    }


async def create_escrow(db: AsyncSession, job: Job, customer: User, contractor: User, amount: Decimal) -> Escrow:
    """Create an escrow record when the customer books.

    Starts *unfunded* — the customer pays separately via the fund endpoint,
    which moves it to ``held``. The platform fee is derived from the
    contractor's effective subscription tier (premium pays less).
    """
    fees = calculate_fees(amount, rate=commission_rate(contractor))

    escrow = Escrow(
        job_id=job.id,
        customer_id=customer.id,
        contractor_id=contractor.id,
        quoted_amount=amount,
        total_amount=amount,
        platform_fee=fees["platform_fee"],
        contractor_payout=fees["contractor_payout"],
        status="unfunded",
        currency="USD",
    )
    db.add(escrow)
    await db.flush()
    return escrow


async def fund_escrow(
    db: AsyncSession,
    job: Job,
    customer: User,
    contractor: User,
    quoted_amount: Decimal,
    card_brand: str,
    card_last4: str,
    payment_gateway_id: Optional[str] = None,
) -> Escrow:
    """Capture the customer's payment and move the escrow to ``held``.

    Reuses the escrow created at booking, or creates one if missing. The
    contractor payout is derived from the contractor's effective tier.
    """
    if job.status != "booked":
        raise ValueError("Job must be booked before funding escrow")
    if quoted_amount <= 0:
        raise ValueError("Amount must be greater than zero")
    if quoted_amount < Decimal(str(settings.MIN_PAYMENT_AMOUNT)):
        raise ValueError(
            f"Minimum charge is {settings.MIN_PAYMENT_AMOUNT:g} {settings.PAYMENT_CURRENCY}."
        )

    fees = calculate_fees(quoted_amount, rate=commission_rate(contractor))

    result = await db.exec(select(Escrow).where(Escrow.job_id == job.id))
    escrow = result.first()
    if escrow is None:
        escrow = Escrow(job_id=job.id, customer_id=customer.id, contractor_id=contractor.id)
    elif escrow.status == "held":
        # Idempotent: already funded. Don't let a second submission overwrite the
        # captured amount or re-issue a receipt.
        return escrow

    if payment_gateway_id:
        # Real gateway (e.g. Stripe PaymentIntent): verify server-side that the
        # payment actually succeeded before trusting the client-supplied id.
        # Without this, a caller could mark an escrow "held" with no real capture.
        if not settings.STRIPE_SECRET_KEY:
            raise ValueError("Payment gateway is not configured; cannot verify payment")
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            intent = await asyncio.to_thread(stripe.PaymentIntent.retrieve, payment_gateway_id)
            if intent.get("status") != "succeeded":
                raise ValueError(f"Payment not completed (status: {intent.get('status')})")
        except ValueError:
            raise
        except Exception as e:  # network/API error while verifying
            raise ValueError(f"Could not verify payment with gateway: {e}")
        capture = {
            "mode": "live",
            "raw": {"payment_intent_id": payment_gateway_id, "status": intent.get("status")},
            "reference_id": payment_gateway_id,
        }
    else:
        capture = await asyncio.to_thread(
            capture_payment,
            quoted_amount, "usd", card_brand, card_last4,
            metadata={"job_id": str(job.id), "customer_id": str(customer.id)},
        )

    escrow.quoted_amount = quoted_amount
    escrow.total_amount = quoted_amount
    escrow.platform_fee = fees["platform_fee"]
    escrow.contractor_payout = fees["contractor_payout"]
    escrow.status = "held"
    escrow.funded_at = datetime.utcnow()
    escrow.card_brand = card_brand
    escrow.card_last4 = card_last4
    escrow.currency = "USD"
    escrow.payment_gateway_id = capture["reference_id"]
    db.add(escrow)
    await db.flush()

    # Issue a customer receipt / invoice for the funded payment
    receipt = Receipt(
        receipt_number=f"RCPT-{job.id}-{escrow.id}",
        job_id=job.id,
        escrow_id=escrow.id,
        customer_id=customer.id,
        contractor_id=contractor.id,
        amount=escrow.total_amount,
        platform_fee=escrow.platform_fee,
        contractor_payout=escrow.contractor_payout,
        currency=escrow.currency,
        card_brand=escrow.card_brand,
        card_last4=escrow.card_last4,
        payment_reference=escrow.payment_gateway_id,
    )
    db.add(receipt)
    return escrow


async def release_escrow(db: AsyncSession, escrow: Escrow) -> Escrow:
    """Release funds to contractor on job completion.

    The contractor payout is credited to the contractor's wallet as *pending*
    (it clears into available balance after the clearing window).
    """
    if escrow.status not in ("held", "disputed"):
        raise ValueError(f"Cannot release escrow in status '{escrow.status}'")
    if escrow.status == "disputed":
        # A disputed escrow must be resolved through the dispute flow, which
        # applies the correct split/refund. Force-releasing would bypass that.
        raise ValueError("Escrow is under dispute; resolve the dispute to release funds")

    escrow.status = "released"
    escrow.released_at = datetime.utcnow()
    escrow.payout_reference_id = f"pay_{escrow.job_id}_{escrow.contractor_id}"

    # Payout to contractor (Stripe Connect when configured, else mock)
    from app.services.payment_gateway import payout_to_contractor
    contractor = await db.get(User, escrow.contractor_id)
    connected = contractor.stripe_account_id if contractor else None
    payout = await asyncio.to_thread(
        payout_to_contractor,
        escrow.contractor_id, escrow.contractor_payout, escrow.currency, connected,
        metadata={"job_id": str(escrow.job_id), "escrow_id": str(escrow.id)},
    )
    escrow.payout_reference_id = payout["reference_id"]

    # Credit contractor wallet (pending → clears later)
    from app.services.wallet_service import credit_pending
    await credit_pending(
        db,
        escrow.contractor_id,
        escrow.contractor_payout,
        reference=escrow.payout_reference_id,
        note=f"Job #{escrow.job_id} released",
    )

    db.add(escrow)
    await db.flush()
    return escrow


async def refund_escrow(db: AsyncSession, escrow: Escrow, reason: Optional[str] = "contractor_cancelled") -> Escrow:
    """Full refund to customer (e.g., contractor no-show)."""
    if escrow.status not in ("held", "disputed"):
        raise ValueError(f"Cannot refund escrow in status '{escrow.status}'")
    
    escrow.status = "refunded"
    escrow.customer_refund = escrow.total_amount
    escrow.refunded_at = datetime.utcnow()
    
    # Mock refund
    await refund_payment(escrow.customer_id, escrow.total_amount, escrow.currency)
    
    db.add(escrow)
    await db.flush()
    return escrow


async def penalty_split_escrow(db: AsyncSession, escrow: Escrow, late_cancellation: bool = True) -> Escrow:
    """Late customer cancellation — split funds with penalty."""
    if escrow.status not in ("held", "disputed"):
        raise ValueError(f"Cannot penalty-split escrow in status '{escrow.status}'")
    
    # Late cancellation: customer gets partial refund, contractor gets compensation
    # Penalty: 20% to contractor as compensation, 80% back to customer
    penalty_pct = Decimal("0.20")
    contractor_compensation = (escrow.total_amount * penalty_pct).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    customer_refund = escrow.total_amount - contractor_compensation
    
    escrow.status = "penalty_split"
    escrow.contractor_payout = contractor_compensation
    escrow.customer_refund = customer_refund
    escrow.released_at = datetime.utcnow()
    escrow.refunded_at = datetime.utcnow()
    
    # Mock payout + refund
    await process_payout(escrow.contractor_id, contractor_compensation, escrow.currency)
    await refund_payment(escrow.customer_id, customer_refund, escrow.currency)

    # Credit contractor compensation to wallet (pending → clears later)
    from app.services.wallet_service import credit_pending
    await credit_pending(
        db,
        escrow.contractor_id,
        contractor_compensation,
        reference=f"pen_{escrow.job_id}",
        note=f"Late-cancel compensation for job #{escrow.job_id}",
    )

    db.add(escrow)
    await db.flush()
    return escrow


async def open_dispute(db: AsyncSession, escrow: Escrow, raiser: User, reason: str) -> Dispute:
    """Customer opens a dispute, freezing the escrow."""
    if escrow.status not in ("held", "completed_pending"):
        raise ValueError(f"Cannot dispute escrow in status '{escrow.status}'")
    
    escrow.status = "disputed"
    db.add(escrow)
    
    dispute = Dispute(
        escrow_id=escrow.id,
        job_id=escrow.job_id,
        raised_by=raiser.id,
        reason=reason,
        status="pending_ai",
    )
    db.add(dispute)
    await db.flush()
    return dispute


async def analyze_and_attach_dispute(
    db: AsyncSession,
    dispute: Dispute,
    chat_history: list,
    job_description: str,
    total_amount: str,
) -> Dispute:
    """Run AI arbitration and persist the result onto the Dispute record.

    Defaults to ``reviewing`` so the dispute is visibly "in progress" while a
    human (or the AI recommendation) finalizes it. The AI's recommended refund
    percentage is stored so admins don't have to transcribe it manually.
    """
    from app.services.gemini_service import analyze_dispute

    result = await analyze_dispute(
        chat_history=chat_history,
        dispute_reason=dispute.reason or "",
        job_description=job_description,
        total_amount=total_amount,
    )
    analysis = result.get("analysis", {})
    dispute.ai_arbitration_summary = json.dumps(analysis)
    if analysis.get("recommended_refund_pct") is not None:
        dispute.ai_recommended_refund_pct = float(analysis["recommended_refund_pct"])
    dispute.status = "reviewing"
    db.add(dispute)
    await db.flush()
    return dispute


async def resolve_dispute(
    db: AsyncSession,
    dispute: Dispute,
    resolution: str,
    refund_pct: float,
    admin_id: int,
) -> Dispute:
    """Admin resolves dispute with a refund percentage (0-100)."""
    dispute.status = "resolved"
    dispute.resolution_notes = resolution
    dispute.ai_recommended_refund_pct = refund_pct
    dispute.resolved_by = admin_id
    dispute.resolved_at = datetime.utcnow()
    
    # Get the escrow
    escrow_result = await db.exec(select(Escrow).where(Escrow.id == dispute.escrow_id))
    escrow = escrow_result.first()
    
    if escrow:
        refund_ratio = Decimal(str(refund_pct)) / Decimal("100")
        refund_amount = (escrow.total_amount * refund_ratio).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        payout_amount = escrow.total_amount - refund_amount
        
        escrow.customer_refund = refund_amount
        escrow.contractor_payout = payout_amount
        
        if refund_pct >= 100:
            escrow.status = "refunded"
            escrow.refunded_at = datetime.utcnow()
            await refund_payment(escrow.customer_id, refund_amount, escrow.currency)
        elif refund_pct <= 0:
            escrow.status = "released"
            escrow.released_at = datetime.utcnow()
            # Credit contractor payout to wallet (pending -> clears later),
            # consistent with the normal release path.
            from app.services.wallet_service import credit_pending
            await credit_pending(
                db, escrow.contractor_id, payout_amount,
                reference=f"disp_{escrow.job_id}",
                note=f"Dispute resolved in contractor's favour (job #{escrow.job_id})",
            )
        else:
            escrow.status = "penalty_split"
            escrow.released_at = datetime.utcnow()
            escrow.refunded_at = datetime.utcnow()
            from app.services.wallet_service import credit_pending
            await credit_pending(
                db, escrow.contractor_id, payout_amount,
                reference=f"disp_{escrow.job_id}",
                note=f"Dispute split payout (job #{escrow.job_id})",
            )
            await refund_payment(escrow.customer_id, refund_amount, escrow.currency)
        
        # Reflect the outcome on the job so dashboards stay consistent.
        job = await db.get(Job, escrow.job_id)
        if job and job.status not in ("completed", "cancelled"):
            if refund_pct >= 100:
                job.status = "cancelled"
            elif refund_pct <= 0:
                job.status = "completed"
            # Partial refunds leave the job state to the admin / participants.
            db.add(job)
        
        db.add(escrow)
    
    # Notify BOTH parties and post a system note into the shared conversation so
    # the resolution is visible to the customer and contractor alike (chat space
    # stays usable afterwards). Failures here must never break the resolution.
    try:
        if escrow:
            conv = (await db.exec(
                select(Conversation).where(Conversation.job_id == escrow.job_id)
            )).first()
            customer = await db.get(User, escrow.customer_id)
            contractor = await db.get(User, escrow.contractor_id)
            summary = (
                f"[SYSTEM] Dispute on Job #{escrow.job_id} resolved by admin.\n"
                f"Refund to customer: {refund_amount} {escrow.currency} ({refund_pct:.0f}%)\n"
                f"Contractor payout: {payout_amount} {escrow.currency}\n"
                f"Resolution: {resolution}"
            )
            if conv:
                db.add(DirectMessage(
                    conversation_id=conv.id,
                    sender_id=admin_id,
                    content=summary,
                ))
            if customer:
                await dispatch_alert(db, customer.id, summary)
            if contractor:
                await dispatch_alert(db, contractor.id, summary)
    except Exception:
        pass

    db.add(dispute)
    await db.flush()
    return dispute
