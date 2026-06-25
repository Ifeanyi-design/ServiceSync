from decimal import Decimal
from datetime import datetime


async def process_payout(contractor_id: int, amount: Decimal, currency: str = "USD") -> dict:
    """
    Mock payout gateway — simulates releasing funds to contractor.
    In production, this would call Stripe Connect, PayPal Payouts, etc.
    """
    reference = f"pay_{contractor_id}_{int(datetime.utcnow().timestamp())}"
    return {
        "success": True,
        "reference_id": reference,
        "amount": str(amount),
        "currency": currency,
        "contractor_id": contractor_id,
        "processed_at": datetime.utcnow().isoformat(),
    }


async def refund_payment(customer_id: int, amount: Decimal, currency: str = "USD") -> dict:
    """
    Mock refund gateway — simulates refunding funds to customer.
    In production, this would call Stripe Refunds, PayPal, etc.
    """
    reference = f"ref_{customer_id}_{int(datetime.utcnow().timestamp())}"
    return {
        "success": True,
        "reference_id": reference,
        "amount": str(amount),
        "currency": currency,
        "customer_id": customer_id,
        "processed_at": datetime.utcnow().isoformat(),
    }
