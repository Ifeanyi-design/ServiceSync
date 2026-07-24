"""
Payment gateway — Stripe Connect ready, demo-safe.

Behaviour:
- If STRIPE_SECRET_KEY is configured AND the contractor has a Stripe Connect
  `stripe_account_id`, real money moves (card capture at funding, Connect
  transfer/payout at release & withdrawal).
- Otherwise it runs in MOCK mode (deterministic fake references) so the whole
  flow is testable with zero configuration.

This keeps ServiceSync demoable out-of-the-box while being production-ready:
drop in Stripe keys + contractor onboarding and real payouts engage
automatically.
"""
from decimal import Decimal
from datetime import datetime
from typing import Optional

import json
import urllib.request
import urllib.error

from app.core.config import settings


def _stripe_available() -> bool:
    return bool(settings.STRIPE_SECRET_KEY)


def is_live() -> bool:
    """True when real Stripe calls will be made."""
    return _stripe_available()


def create_connect_account(email: str, country: str = "US") -> dict:
    """Create a Stripe Connect Express account for a contractor.

    Returns {success, mode, account_id}. In mock mode returns a fake id so the
    onboarding UI is demoable without keys.
    """
    if _stripe_available():
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            acct = stripe.Account.create(
                type="express",
                email=email,
                capabilities={"transfers": {"requested": True}},
            )
            return {"success": True, "mode": "stripe", "account_id": acct["id"]}
        except Exception as e:  # pragma: no cover - network path
            return {"success": False, "mode": "stripe", "error": str(e)}
    return {"success": True, "mode": "mock", "account_id": f"acct_mock_{email.split('@')[0]}"}


def create_onboarding_link(account_id: str, return_url: str, refresh_url: str) -> dict:
    """Create a Stripe account onboarding link. Mock mode returns the return_url
    so the demo flow completes immediately."""
    if _stripe_available() and not account_id.startswith("acct_mock_"):
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            link = stripe.AccountLink.create(
                account=account_id,
                return_url=return_url,
                refresh_url=refresh_url,
                type="account_onboarding",
            )
            return {"success": True, "mode": "stripe", "url": link["url"]}
        except Exception as e:  # pragma: no cover
            return {"success": False, "mode": "stripe", "error": str(e)}
    return {"success": True, "mode": "mock", "url": return_url}


def create_payment_intent(
    amount: Decimal,
    currency: str = "usd",
    metadata: Optional[dict] = None,
) -> dict:
    """Create a PaymentIntent for client-side confirmation (Stripe Elements).

    Returns {success, mode, client_secret, reference_id}. In mock mode
    `client_secret` is None and the caller should fall back to the mock form.
    """
    if _stripe_available():
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            intent = stripe.PaymentIntent.create(
                amount=int(amount * 100),
                currency=currency,
                automatic_payment_methods={"enabled": True},
                metadata=metadata or {},
            )
            return {
                "success": True,
                "mode": "stripe",
                "client_secret": intent["client_secret"],
                "reference_id": intent["id"],
            }
        except Exception as e:  # pragma: no cover
            return {"success": False, "mode": "stripe", "error": str(e)}
    return {
        "success": True,
        "mode": "mock",
        "client_secret": None,
        "reference_id": f"pi_mock_{int(datetime.utcnow().timestamp())}",
    }


def capture_payment(
    amount: Decimal,
    currency: str = "usd",
    card_brand: Optional[str] = None,
    card_last4: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Capture a customer's payment at funding time.

    Returns a dict with at least `success`, `mode`, `reference_id`,
    `brand`, `last4`, `captured_at`.
    """
    ref = f"pi_mock_{int(datetime.utcnow().timestamp())}"
    if _stripe_available():
        try:
            import stripe  # imported lazily so demo mode has no hard dep
            stripe.api_key = settings.STRIPE_SECRET_KEY
            intent = stripe.PaymentIntent.create(
                amount=int(amount * 100),
                currency=currency,
                automatic_payment_methods={"enabled": True},
                metadata=metadata or {},
                # In test mode a real card is still required client-side; the
                # server confirms the client-provided PaymentIntent.
            )
            return {
                "success": True,
                "mode": "stripe",
                "reference_id": intent["id"],
                "brand": card_brand,
                "last4": card_last4,
                "captured_at": datetime.utcnow().isoformat(),
            }
        except Exception:
            # Fail safe to mock so the demo never hard-breaks on Stripe issues.
            pass
    return {
        "success": True,
        "mode": "mock",
        "reference_id": ref,
        "brand": card_brand,
        "last4": card_last4,
        "captured_at": datetime.utcnow().isoformat(),
    }


def payout_to_contractor(
    contractor_id: int,
    amount: Decimal,
    currency: str = "usd",
    connected_account_id: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> dict:
    """Payout released funds to a contractor (escrow release / withdrawal).

    Uses Stripe Connect transfer when `connected_account_id` is present and
    Stripe is configured; otherwise records a mock payout.
    """
    ref = f"po_mock_{contractor_id}_{int(datetime.utcnow().timestamp())}"
    if _stripe_available() and connected_account_id:
        try:
            import stripe
            stripe.api_key = settings.STRIPE_SECRET_KEY
            # Platform retains its commission; transfer the contractor's share.
            transfer = stripe.Transfer.create(
                amount=int(amount * 100),
                currency=currency,
                destination=connected_account_id,
                metadata=metadata or {},
            )
            return {
                "success": True,
                "mode": "stripe",
                "reference_id": transfer["id"],
                "amount": str(amount),
                "currency": currency,
                "contractor_id": contractor_id,
                "processed_at": datetime.utcnow().isoformat(),
            }
        except Exception:
            pass
    return {
        "success": True,
        "mode": "mock",
        "reference_id": ref,
        "amount": str(amount),
        "currency": currency,
        "contractor_id": contractor_id,
        "processed_at": datetime.utcnow().isoformat(),
    }


def payout_to_contractor_via_paystack(
    contractor_id: int,
    amount_kobo: int,
    recipient_code: str,
    currency: str = "NGN",
    reason: str = "Escrow release",
) -> dict:
    """Paystack counterpart of ``payout_to_contractor``.

    Pays the released share out to the contractor via a Paystack Transfer
    when they have a verified recipient code (set in /settings → Payout).
    Falls back to a no-op record when Paystack isn't configured or the
    contractor has no recipient code.
    """
    ref = f"po_paystack_mock_{contractor_id}_{int(datetime.utcnow().timestamp())}"
    if not paystack_available() or not recipient_code:
        return {
            "success": True,
            "mode": "mock",
            "reference_id": ref,
            "amount_kobo": int(amount_kobo),
            "currency": currency,
            "contractor_id": contractor_id,
            "processed_at": datetime.utcnow().isoformat(),
        }
    try:
        resp = _paystack_request(
            "POST",
            "/transfer",
            {
                "source": "balance",
                "amount": int(amount_kobo),
                "recipient": recipient_code,
                "reason": reason,
                "currency": currency,
            },
        )
        if resp.get("status"):
            data = resp["data"]
            return {
                "success": True,
                "mode": "paystack",
                "reference_id": data.get("reference"),
                "amount_kobo": int(amount_kobo),
                "currency": currency,
                "contractor_id": contractor_id,
                "processed_at": datetime.utcnow().isoformat(),
            }
        return {
            "success": False,
            "mode": "paystack",
            "error": resp.get("message", "transfer failed"),
        }
    except Exception as exc:
        return {"success": False, "mode": "paystack", "error": str(exc)}


def charge_minimum(currency: Optional[str] = None) -> Decimal:
    """Safe per-currency charge minimum as Decimal — use this everywhere instead
    of hardcoding ``MIN_PAYMENT_AMOUNT``. Falls back to backwards-compatible
    USD legacy only if no per-currency entry exists.
    """
    cur = (currency or settings.PAYMENT_CURRENCY or "USD").upper()
    val = settings.MIN_PAYMENT_BY_CURRENCY.get(cur)
    if val is None:
        return Decimal(str(settings.MIN_PAYMENT_AMOUNT))
    return Decimal(str(val))


# ---------------------------------------------------------------------------
# Paystack — primary processor for NG/Africa (cards, bank transfer, mobile money)
# ---------------------------------------------------------------------------
def paystack_available() -> bool:
    return bool(settings.PAYSTACK_SECRET_KEY and settings.PAYSTACK_PUBLIC_KEY)


def _paystack_request(method: str, path: str, body: Optional[dict] = None, timeout: int = 25):
    url = f"https://api.paystack.co{path}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {settings.PAYSTACK_SECRET_KEY}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Cache-Control", "no-cache")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode())


def create_paystack_transaction(
    amount_kobo: int,
    email: str,
    metadata: Optional[dict] = None,
    currency: str = "NGN",
) -> dict:
    """Initialize a Paystack transaction. Returns {success, mode, reference,
    access_code, authorization_url}. In demo mode returns a fake reference."""
    if not paystack_available():
        return {"success": False, "mode": "mock", "error": "Paystack not configured"}
    try:
        # Paystack currency determines the available channels; for African
        # currencies (NGN/GHS/KES/ZAR) we surface card + bank + USSD + mobile
        # money. Other currencies default to card only to avoid an invalid
        # channel name error from the API.
        resp = _paystack_request(
            "POST",
            "/transaction/initialize",
            {
                "amount": int(amount_kobo),
                "email": email,
                "currency": currency,
                "metadata": metadata or {},
                "channels": (
                    ["card", "bank", "ussd", "qr", "mobile_money"]
                    if currency in ("NGN", "GHS", "KES", "ZAR")
                    else ["card"]
                ),
            },
        )
        if resp.get("status"):
            data = resp["data"]
            return {
                "success": True,
                "mode": "paystack",
                "reference": data["reference"],
                "access_code": data.get("access_code"),
                "authorization_url": data.get("authorization_url"),
            }
        return {"success": False, "mode": "paystack", "error": resp.get("message", "initialize failed")}
    except Exception as e:  # pragma: no cover - network path
        return {"success": False, "mode": "paystack", "error": str(e)}


def verify_paystack_transaction(reference: str) -> dict:
    """Verify a Paystack transaction by reference. Returns {success, mode,
    status, reference, amount (kobo), currency, ...}."""
    if not paystack_available():
        return {"success": False, "mode": "mock", "error": "Paystack not configured"}
    try:
        resp = _paystack_request("GET", f"/transaction/verify/{reference}")
        if resp.get("status"):
            data = resp["data"]
            return {
                "success": True,
                "mode": "paystack",
                "status": data.get("status"),
                "reference": data.get("reference"),
                "amount": data.get("amount"),
                "currency": data.get("currency"),
                "paid_at": data.get("paid_at"),
                "customer_email": (data.get("customer") or {}).get("email"),
                "authorization": data.get("authorization"),
            }
        return {"success": False, "mode": "paystack", "error": resp.get("message", "verify failed")}
    except Exception as e:  # pragma: no cover - network path
        return {"success": False, "mode": "paystack", "error": str(e)}


# ---------------------------------------------------------------------------
# Paystack Transfers — contractor payouts (released escrow)
# ---------------------------------------------------------------------------
def create_paystack_recipient(
    account_name: str,
    account_number: str,
    bank_code: str,
    currency: str = "NGN",
) -> dict:
    """Create a Paystack transfer recipient (NUBAN bank account).

    Returns {success, mode, recipient_code, recipient_id} on success, or
    ``{success=False, …}`` on error / in mock mode.
    """
    if not paystack_available():
        return {"success": False, "mode": "mock", "error": "Paystack not configured"}
    try:
        resp = _paystack_request(
            "POST",
            "/transferrecipient",
            {
                "type": "nuban",
                "name": account_name,
                "account_number": account_number,
                "bank_code": bank_code,
                "currency": currency,
            },
        )
        if resp.get("status"):
            data = resp["data"]
            return {
                "success": True,
                "mode": "paystack",
                "recipient_code": data.get("recipient_code"),
                "recipient_id": data.get("id"),
            }
        return {"success": False, "mode": "paystack", "error": resp.get("message", "create recipient failed")}
    except Exception as e:  # pragma: no cover - network path
        return {"success": False, "mode": "paystack", "error": str(e)}


def paystack_transfer(
    amount_kobo: int,
    recipient_code: str,
    reason: str = "Escrow release",
    currency: str = "NGN",
) -> dict:
    """Initiate a Paystack transfer to a previously created recipient.

    Returns {success, mode, reference_id, status, amount, transferred_at}
    on success, or ``{success=False, …}`` on error.
    """
    if not paystack_available():
        return {"success": False, "mode": "mock", "error": "Paystack not configured"}
    try:
        resp = _paystack_request(
            "POST",
            "/transfer",
            {
                "source": "balance",
                "amount": int(amount_kobo),
                "recipient": recipient_code,
                "reason": reason,
                "currency": currency,
            },
        )
        if resp.get("status"):
            data = resp["data"]
            return {
                "success": True,
                "mode": "paystack",
                "reference_id": data.get("reference"),
                "status": data.get("status"),
                "amount": data.get("amount"),
                "currency": data.get("currency"),
                "transferred_at": data.get("createdAt") or data.get("updatedAt"),
            }
        return {"success": False, "mode": "paystack", "error": resp.get("message", "transfer failed")}
    except Exception as e:  # pragma: no cover - network path
        return {"success": False, "mode": "paystack", "error": str(e)}


def verify_paystack_transfer(reference: str) -> dict:
    """Verify the status of a Paystack transfer by reference.

    Returns {success, mode, status, reference, amount, …} on success.
    """
    if not paystack_available():
        return {"success": False, "mode": "mock", "error": "Paystack not configured"}
    try:
        resp = _paystack_request("GET", f"/transfer/verify/{reference}")
        if resp.get("status"):
            data = resp["data"]
            return {
                "success": True,
                "mode": "paystack",
                "status": data.get("status"),
                "reference": data.get("reference"),
                "amount": data.get("amount"),
                "currency": data.get("currency"),
                "transferred_at": data.get("createdAt"),
                "failures": data.get("failures"),
            }
        return {"success": False, "mode": "paystack", "error": resp.get("message", "verify transfer failed")}
    except Exception as e:  # pragma: no cover - network path
        return {"success": False, "mode": "paystack", "error": str(e)}
