from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.models.all_models import Escrow, Dispute, Job, User
from app.services.payout_gateway import process_payout, refund_payment

# Platform fee percentage
PLATFORM_FEE_PCT = Decimal("0.10")  # 10%


def calculate_fees(amount: Decimal) -> dict:
    """Calculate platform fee and contractor payout from total amount."""
    platform_fee = (amount * PLATFORM_FEE_PCT).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    contractor_payout = amount - platform_fee
    return {
        "total_amount": amount,
        "platform_fee": platform_fee,
        "contractor_payout": contractor_payout,
    }


async def create_escrow(db: AsyncSession, job: Job, customer: User, contractor: User, amount: Decimal) -> Escrow:
    """Create an escrow record and hold funds when customer books."""
    fees = calculate_fees(amount)
    
    escrow = Escrow(
        job_id=job.id,
        customer_id=customer.id,
        contractor_id=contractor.id,
        total_amount=fees["total_amount"],
        platform_fee=fees["platform_fee"],
        contractor_payout=fees["contractor_payout"],
        status="held",
        funded_at=datetime.utcnow(),
        currency="USD",
    )
    db.add(escrow)
    await db.flush()
    return escrow


async def release_escrow(db: AsyncSession, escrow: Escrow) -> Escrow:
    """Release funds to contractor on job completion."""
    if escrow.status not in ("held", "disputed"):
        raise ValueError(f"Cannot release escrow in status '{escrow.status}'")
    
    escrow.status = "released"
    escrow.released_at = datetime.utcnow()
    escrow.payout_reference_id = f"pay_{escrow.job_id}_{escrow.contractor_id}"
    
    # Mock payout
    await process_payout(escrow.contractor_id, escrow.contractor_payout, escrow.currency)
    
    db.add(escrow)
    await db.flush()
    return escrow


async def refund_escrow(db: AsyncSession, escrow: Escrow, reason: str = "contractor_cancelled") -> Escrow:
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
    if escrow.status not in ("held",):
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
    
    db.add(escrow)
    await db.flush()
    return escrow


async def open_dispute(db: AsyncSession, escrow: Escrow, raiser: User, reason: str) -> Dispute:
    """Customer opens a dispute, freezing the escrow."""
    if escrow.status != "held":
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
            await process_payout(escrow.contractor_id, payout_amount, escrow.currency)
        else:
            escrow.status = "penalty_split"
            escrow.released_at = datetime.utcnow()
            escrow.refunded_at = datetime.utcnow()
            await process_payout(escrow.contractor_id, payout_amount, escrow.currency)
            await refund_payment(escrow.customer_id, refund_amount, escrow.currency)
        
        db.add(escrow)
    
    db.add(dispute)
    await db.flush()
    return dispute
