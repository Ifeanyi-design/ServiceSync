"""
Cross-platform alert dispatch service.
Sends notifications to contractors via their connected channels (WhatsApp, Telegram, Messenger).
"""
import httpx
from typing import Optional
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select

from app.models.all_models import OmnichannelIntegration, User


async def send_platform_message(platform: str, recipient_id: str, text: str, access_token: str, reply_markup: dict = None) -> bool:
    """Send a message to a specific platform. Returns True on success."""
    async with httpx.AsyncClient() as client:
        try:
            if platform == "whatsapp":
                url = "https://graph.facebook.com/v17.0/me/messages"
                headers = {"Authorization": f"Bearer {access_token}"}
                payload = {
                    "messaging_product": "whatsapp",
                    "to": recipient_id,
                    "text": {"body": text},
                }
                resp = await client.post(url, headers=headers, json=payload)
                return resp.status_code == 200

            elif platform == "telegram":
                url = f"https://api.telegram.org/bot{access_token}/sendMessage"
                payload = {"chat_id": recipient_id, "text": text, "parse_mode": "HTML"}
                if reply_markup:
                    payload["reply_markup"] = reply_markup
                resp = await client.post(url, json=payload)
                return resp.status_code == 200

            elif platform == "messenger":
                url = f"https://graph.facebook.com/v17.0/me/messages?access_token={access_token}"
                payload = {
                    "recipient": {"id": recipient_id},
                    "message": {"text": text},
                }
                resp = await client.post(url, json=payload)
                return resp.status_code == 200

        except Exception:
            pass
    return False


async def dispatch_alert(db: AsyncSession, contractor_id: int, message: str) -> dict:
    """
    Send an alert to a contractor across all their active connected channels.
    Returns a dict of {platform: success_bool}.
    """
    result = await db.exec(
        select(OmnichannelIntegration).where(
            OmnichannelIntegration.contractor_id == contractor_id,
            OmnichannelIntegration.is_active == True,
        )
    )
    integrations = result.all()
    results = {}

    for integ in integrations:
        success = await send_platform_message(
            platform=integ.platform,
            recipient_id=integ.platform_account_id,
            text=message,
            access_token=integ.access_token,
        )
        results[integ.platform] = success

    return results


async def alert_new_booking(db: AsyncSession, contractor: User, job, customer: User) -> dict:
    """Alert contractor about a new booking via all connected channels."""
    location_parts = [
        getattr(job, "area", None),
        getattr(job, "city", None),
        getattr(job, "state_or_province", None),
    ]
    location_str = ", ".join(p for p in location_parts if p) or "Location not specified"

    message = (
        f"New Booking!\n\n"
        f"Customer: {customer.full_name}\n"
        f"Job: {job.description}\n"
        f"Location: {location_str}\n"
        f"Urgency: {getattr(job, 'urgency', 'normal')}\n\n"
        f"Open ServiceSync to view details and start chatting."
    )
    return await dispatch_alert(db, contractor.id, message)


async def alert_new_message(db: AsyncSession, contractor_id: int, sender_name: str, preview: str) -> dict:
    """Alert contractor about a new message via all connected channels."""
    message = (
        f"New Message from {sender_name}:\n\n"
        f'"{preview[:200]}"\n\n'
        f"Open ServiceSync to reply."
    )
    return await dispatch_alert(db, contractor_id, message)


async def alert_dispute_opened(db: AsyncSession, contractor: User, job_id: int, reason: str) -> dict:
    """Alert contractor that a dispute has been opened on their job."""
    message = (
        f"Dispute Opened — Job #{job_id}\n\n"
        f"Reason: {reason}\n\n"
        f"Escrow funds have been frozen. Open ServiceSync to review and respond."
    )
    return await dispatch_alert(db, contractor.id, message)


async def alert_escrow_released(db: AsyncSession, contractor: User, job_id: int, amount: str) -> dict:
    """Alert contractor that escrow funds have been released."""
    message = (
        f"Payment Released — Job #{job_id}\n\n"
        f"Amount: {amount} has been transferred to your account.\n\n"
        f"Open ServiceSync for payout details."
    )
    return await dispatch_alert(db, contractor.id, message)
