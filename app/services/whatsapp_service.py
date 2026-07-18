"""WhatsApp Cloud API integration (Meta Graph).

- ``send_whatsapp`` posts a text message via the Graph API.
- ``verify_whatsapp_signature`` validates the ``X-Hub-Signature-256`` header.

Both are no-ops / safe when WHATSAPP_TOKEN is not configured.
"""
import hashlib
import hmac
import logging
from typing import Optional

import httpx

from app.core.config import settings

logger = logging.getLogger("services.whatsapp")

GRAPH_URL = "https://graph.facebook.com/v19.0"


def verify_whatsapp_signature(raw_body: bytes, signature_header: Optional[str]) -> bool:
    """Return True if ``X-Hub-Signature-256`` matches HMAC-SHA256 of the body."""
    if not settings.WHATSAPP_APP_SECRET or not signature_header:
        return False
    expected = hmac.new(
        settings.WHATSAPP_APP_SECRET.encode(),
        raw_body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(signature_header, f"sha256={expected}")


async def send_whatsapp(to: str, text: str) -> bool:
    """Send a WhatsApp text message. Returns True on success."""
    if not (settings.WHATSAPP_TOKEN and settings.WHATSAPP_PHONE_NUMBER_ID):
        logger.warning("WhatsApp not configured; skipping message to %s", to)
        return False
    url = f"{GRAPH_URL}/{settings.WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": text},
    }
    headers = {
        "Authorization": f"Bearer {settings.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(url, json=payload, headers=headers)
            if r.status_code >= 400:
                logger.error("WhatsApp send failed (%s): %s", r.status_code, r.text)
                return False
        return True
    except Exception as e:
        logger.error("WhatsApp send error: %s", e)
        return False
