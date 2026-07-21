from fastapi import APIRouter, Depends, HTTPException, Request, Response, BackgroundTasks
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import Any, Optional
import hmac
import hashlib
import json
from decimal import Decimal
import httpx

from app.api.dependencies import get_db
from app.core.database import async_session_maker
from app.models.all_models import OmnichannelIntegration, User, Conversation, DirectMessage, AIDraft, StripeEvent
from datetime import datetime
import logging

logger = logging.getLogger(__name__)
from app.core.config import settings
from app.models.audit_log import AIOperationsAuditLog
from app.services.gemini_service import generate_contractor_reply

router = APIRouter()

# Meta webhook verify token + app secret now come from environment/config
# (see app.core.config settings.META_VERIFY_TOKEN / META_APP_SECRET).


@router.post("/stripe")
async def stripe_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Hardened Stripe webhook: verifies the signature and records each event
    once (idempotent) using the StripeEvent table.

    - Requires STRIPE_WEBHOOK_SECRET; rejects unverified payloads.
    - Duplicate deliveries (same event id) are acknowledged without reprocessing.
    """
    payload = await request.body()
    sig_header = request.headers.get("stripe-signature")

    if not settings.STRIPE_WEBHOOK_SECRET:
        raise HTTPException(status_code=503, detail="Stripe webhooks not configured")
    if not sig_header:
        raise HTTPException(status_code=400, detail="Missing Stripe signature")

    try:
        import stripe
        event = stripe.Webhook.construct_event(
            payload, sig_header, settings.STRIPE_WEBHOOK_SECRET
        )
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid payload")
    except Exception:
        # Includes stripe.error.SignatureVerificationError
        raise HTTPException(status_code=400, detail="Signature verification failed")

    event_id = event.get("id")
    event_type = event.get("type", "unknown")

    # Idempotency: skip if we've already stored this event.
    existing = await db.exec(select(StripeEvent).where(StripeEvent.stripe_event_id == event_id))
    if existing.first():
        return {"status": "duplicate", "event_id": event_id}

    record = StripeEvent(
        stripe_event_id=event_id,
        event_type=event_type,
        processed=False,
        payload=dict(event),
    )
    db.add(record)
    await db.commit()

    # Act on the events we care about, keeping escrow in sync with Stripe.
    try:
        await _handle_stripe_event(db, event_type, event)
        record.processed = True
        await db.commit()
    except Exception as e:  # pragma: no cover - defensive
        # Event is stored; leave processed=False for later reconciliation.
        import logging
        logging.getLogger(__name__).error("Stripe event %s handling failed: %s", event_id, e)

    return {"status": "received", "event_id": event_id, "type": event_type}


async def _handle_stripe_event(db: AsyncSession, event_type: str, event: dict) -> None:
    """Sync escrow state from Stripe events (idempotent — safe to re-run)."""
    from datetime import datetime
    from app.models.all_models import Escrow

    obj = (event.get("data") or {}).get("object") or {}

    if event_type == "payment_intent.succeeded":
        intent_id = obj.get("id")
        if not intent_id:
            return
        res = await db.exec(select(Escrow).where(Escrow.payment_gateway_id == intent_id))
        escrow = res.first()
        if escrow and escrow.status in ("unfunded", "pending", "held"):
            # Authoritative: Stripe confirms the capture, so ensure we land on "held"
            # even if the client's funding callback was lost/raced the webhook.
            if escrow.status != "held":
                escrow.status = "held"
                escrow.funded_at = datetime.utcnow()
                db.add(escrow)
                await db.commit()

    elif event_type == "payment_intent.payment_failed":
        intent_id = obj.get("id")
        if not intent_id:
            return
        res = await db.exec(select(Escrow).where(Escrow.payment_gateway_id == intent_id))
        escrow = res.first()
        if escrow and escrow.status == "unfunded":
            # Leave as unfunded so the customer can retry; just record the failure.
            db.add(escrow)
            await db.commit()

    elif event_type in ("charge.refunded", "charge.refund.updated"):
        intent_id = obj.get("payment_intent")
        if not intent_id:
            return
        res = await db.exec(select(Escrow).where(Escrow.payment_gateway_id == intent_id))
        escrow = res.first()
        if escrow and escrow.status not in ("refunded", "disputed", "penalty_split"):
            escrow.status = "refunded"
            escrow.refunded_at = datetime.utcnow()
            db.add(escrow)
            await db.commit()


@router.post("/paystack")
async def paystack_webhook(request: Request, db: AsyncSession = Depends(get_db)) -> Any:
    """Paystack webhook. Verifies the HMAC-SHA512 signature (when a webhook
    secret is configured) and fulfils escrow on ``charge.success`` — the
    authoritative, idempotent source of truth for funding."""
    raw = await request.body()
    sig = request.headers.get("x-paystack-signature")
    if settings.PAYSTACK_WEBHOOK_SECRET:
        if not sig:
            raise HTTPException(status_code=400, detail="Missing Paystack signature")
        expected = hmac.new(settings.PAYSTACK_WEBHOOK_SECRET.encode(), raw, hashlib.sha512).hexdigest()
        if not hmac.compare_digest(expected, sig):
            raise HTTPException(status_code=400, detail="Invalid Paystack signature")

    try:
        payload = json.loads(raw or b"{}")
    except Exception:
        return {"status": "ignored"}

    event_type = payload.get("event")
    data = payload.get("data") or {}
    if event_type != "charge.success":
        return {"status": "received", "event": event_type}

    reference = data.get("reference")
    if not reference:
        return {"status": "ignored"}
    amount = Decimal(str(data.get("amount") or 0)) / Decimal("100")
    currency = data.get("currency")
    auth = data.get("authorization") or {}
    metadata = data.get("metadata") or {}

    from app.services.escrow_service import mark_escrow_paid_by_reference
    try:
        await mark_escrow_paid_by_reference(
            db, reference,
            amount=amount, currency=currency,
            card_brand=auth.get("card_type") or "Paystack",
            card_last4=auth.get("last4") or "",
            metadata=metadata,
        )
    except Exception as e:  # pragma: no cover - defensive
        logger.exception("paystack webhook handling failed: %s", e)
        return {"status": "error", "detail": str(e)}
    return {"status": "received", "event": event_type}


@router.get("/{platform}")
async def verify_webhook(
    platform: str,
    request: Request
) -> Any:
    """
    Handle webhook verification for Meta platforms (WhatsApp, Messenger).
    """
    if platform not in ["whatsapp", "messenger"]:
        raise HTTPException(status_code=400, detail="Unsupported platform for verification")

    hub_mode = request.query_params.get("hub.mode")
    hub_challenge = request.query_params.get("hub.challenge")
    hub_verify_token = request.query_params.get("hub.verify_token")

    if hub_mode == "subscribe" and hub_verify_token == settings.META_VERIFY_TOKEN:
        return Response(content=hub_challenge, media_type="text/plain")
    
    raise HTTPException(status_code=403, detail="Verification failed")

async def send_outbound_message(platform: str, recipient_id: str, text: str, access_token: str):
    """
    Asynchronous background task to send messages back to the user via platform API.
    """
    async with httpx.AsyncClient() as client:
        try:
            if platform == "whatsapp":
                url = "https://graph.facebook.com/v17.0/me/messages"
                headers = {"Authorization": f"Bearer {access_token}"}
                payload = {
                    "messaging_product": "whatsapp",
                    "to": recipient_id,
                    "text": {"body": text}
                }
                await client.post(url, headers=headers, json=payload)
                print(f"[WhatsApp] Sent to {recipient_id}: {text}")

            elif platform == "telegram":
                url = f"https://api.telegram.org/bot{access_token}/sendMessage"
                payload = {"chat_id": recipient_id, "text": text}
                await client.post(url, json=payload)
                print(f"[Telegram] Sent to {recipient_id}: {text}")

            elif platform == "messenger":
                url = f"https://graph.facebook.com/v17.0/me/messages?access_token={access_token}"
                payload = {
                    "recipient": {"id": recipient_id},
                    "message": {"text": text}
                }
                await client.post(url, json=payload)
                print(f"[Messenger] Sent to {recipient_id}: {text}")
        except Exception as e:
            print(f"Failed to send outbound message: {str(e)}")

@router.post("/{platform}/{bot_token:path}")
@router.post("/{platform}")
async def receive_webhook(
    platform: str,
    request: Request,
    background_tasks: BackgroundTasks,
    bot_token: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Handle incoming messages / callback queries from external platforms.
    Public endpoint — Telegram/Meta sign it their own way (we validate the
    Telegram secret token when configured).

    For Telegram, the bot token is accepted either in the URL path
    (`/webhooks/telegram/<BOT_TOKEN>`) or as the `bot_token` query param, so the
    integration can be resolved by its token.
    """
    # Optional Telegram secret-token check (set via BotFather / setWebhook header).
    if platform == "telegram" and settings.TELEGRAM_WEBHOOK_SECRET:
        if request.headers.get("X-Telegram-Bot-Api-Secret-Token") != settings.TELEGRAM_WEBHOOK_SECRET:
            raise HTTPException(status_code=403, detail="Invalid Telegram secret token")

    # Verify Meta (WhatsApp/Messenger) payload signature when an app secret is set.
    if platform in ("whatsapp", "messenger") and settings.META_APP_SECRET:
        import hmac
        import json as _json
        from hashlib import sha256
        raw = await request.body()
        sig = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(settings.META_APP_SECRET.encode(), raw, sha256).hexdigest()
        if not hmac.compare_digest(sig, expected):
            logger.warning("webhook/%s: invalid Meta signature", platform)
            raise HTTPException(status_code=403, detail="Invalid signature")
        try:
            payload = _json.loads(raw)
        except Exception:
            return {"status": "ignored"}
    else:
        try:
            payload = await request.json()
        except Exception:
            logger.warning("webhook/%s: invalid JSON body", platform)
            return {"status": "ignored"}

    logger.info("webhook/%s: received payload keys=%s", platform, list(payload.keys()))

    # Resolve the Telegram bot token (path > query).
    if platform == "telegram" and not bot_token:
        bot_token = request.query_params.get("bot_token")

    sender_id = None
    recipient_id = None
    message_text = None

    # ---- Telegram: callback query (approve / dismiss AI draft) ----
    if platform == "telegram" and "callback_query" in payload:
        return await _handle_telegram_callback(payload, db)

    # ---- Payload parsers ----
    if platform == "whatsapp":
        try:
            entry = payload["entry"][0]["changes"][0]["value"]
            message = entry["messages"][0]
            sender_id = message["from"]
            recipient_id = entry["metadata"]["display_phone_number"]
            message_text = message["text"]["body"]
        except (KeyError, IndexError, TypeError):
            return {"status": "ignored"}

    elif platform == "telegram":
        try:
            message = payload["message"]
            sender_id = str(message["from"]["id"])
            recipient_id = str(message["chat"]["id"])
            message_text = message.get("text", "")
        except (KeyError, TypeError):
            return {"status": "ignored"}

    elif platform == "messenger":
        try:
            entry = payload["entry"][0]["messaging"][0]
            sender_id = entry["sender"]["id"]
            recipient_id = entry["recipient"]["id"]
            message_text = entry["message"]["text"]
        except (KeyError, IndexError, TypeError):
            return {"status": "ignored"}

    else:
        raise HTTPException(status_code=400, detail="Unsupported platform")

    if not sender_id or not recipient_id or not message_text:
        return {"status": "ignored"}

    # Step A: find the integration.
    #  - Telegram: match by bot token (access_token) since the message arrives at
    #    the bot; the chat id is recorded as platform_account_id for callbacks.
    #  - Others: match by the platform account id (the contractor's handle).
    if platform == "telegram" and bot_token:
        integration_query = select(OmnichannelIntegration).where(
            OmnichannelIntegration.platform == "telegram",
            OmnichannelIntegration.access_token == bot_token,
            OmnichannelIntegration.is_active == True,
        )
    else:
        integration_query = select(OmnichannelIntegration).where(
            OmnichannelIntegration.platform == platform,
            OmnichannelIntegration.platform_account_id == recipient_id,
            OmnichannelIntegration.is_active == True,
        )
    integration = (await db.exec(integration_query)).first()
    # Last-resort for Telegram: the webhook URL may not carry the token (e.g. set
    # manually), so try matching by the chat id stored as platform_account_id.
    if not integration and platform == "telegram":
        integration = (await db.exec(
            select(OmnichannelIntegration).where(
                OmnichannelIntegration.platform == "telegram",
                OmnichannelIntegration.platform_account_id == recipient_id,
                OmnichannelIntegration.is_active == True,
            )
        )).first()
    if not integration:
        logger.warning("webhook/%s: no active integration (token=%s, recipient=%s)", platform, bool(bot_token), recipient_id)
        return {"status": "unrecognized_integration"}

    contractor = await db.get(User, integration.contractor_id)
    if not contractor:
        return {"status": "contractor_not_found"}

    # Step B: contractor context
    contractor_context = {
        "profession": contractor.profession,
        "base_pricing": contractor.base_pricing,
        "service_radius_miles": contractor.service_radius_miles,
        "working_hours_start": contractor.working_hours_start,
        "working_hours_end": contractor.working_hours_end,
        "ai_tone_preference": contractor.ai_tone_preference,
    }

    # Step C: AI reply (never let a model failure break the webhook)
    try:
        bot_reply = await generate_contractor_reply(message_text, contractor_context)
    except Exception as e:
        logger.exception("webhook/%s: AI reply failed: %s", platform, e)
        bot_reply = "Thanks for your message — the contractor will get back to you shortly."

    # Step D: audit log
    audit_log = AIOperationsAuditLog(
        action_type="omnichannel_auto_reply",
        user_id=contractor.id,
        gemini_model_version=settings.GEMINI_MODEL,
        input_context={"incoming_message": message_text, "context": contractor_context},
        raw_ai_response=bot_reply,
        structured_decision={"platform": platform, "sender": sender_id, "recipient": recipient_id},
        status="success",
    )
    db.add(audit_log)
    await db.commit()

    # Step E: reply back to the user
    background_tasks.add_task(
        send_outbound_message,
        platform=platform,
        recipient_id=sender_id,
        text=bot_reply,
        access_token=integration.access_token,
    )
    return {"status": "success"}


async def _handle_telegram_callback(payload: dict, db: AsyncSession) -> Any:
    """Approve / dismiss an AI-generated draft from the Telegram inline keyboard."""
    callback = payload["callback_query"]
    callback_id = callback.get("id", "")
    data = callback.get("data", "")
    try:
        chat_id = str(callback["message"]["chat"]["id"])
        message_id = callback["message"]["message_id"]
    except (KeyError, TypeError):
        return {"status": "ignored"}

    logger.info("telegram callback: data=%s chat=%s", data, chat_id)

    # Locate the integration that owns this chat (platform_account_id == chat id)
    integ = (await db.exec(
        select(OmnichannelIntegration).where(
            OmnichannelIntegration.platform == "telegram",
            OmnichannelIntegration.platform_account_id == chat_id,
            OmnichannelIntegration.is_active == True,
        )
    )).first()
    if not integ:
        logger.warning("telegram callback: no integration for chat=%s", chat_id)
        return {"status": "no_integration"}
    bot_token = integ.access_token

    async with httpx.AsyncClient(timeout=10) as client:
        # Always answer the callback first to stop the spinner.
        await client.post(
            f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
            json={"callback_query_id": callback_id},
        )

        if data.startswith("approve_draft:") or data.startswith("dismiss_draft:"):
            try:
                parts = data.split(":")
                action = parts[0]          # approve_draft / dismiss_draft
                conversation_id = int(parts[1])
                draft_id = int(parts[2])
            except (IndexError, ValueError):
                logger.warning("telegram callback: malformed data=%s", data)
                return {"status": "bad_data"}

            draft = (await db.exec(select(AIDraft).where(AIDraft.id == draft_id))).first()
            if not draft or draft.conversation_id != conversation_id or draft.status != "pending":
                logger.info("telegram callback: draft %s not actionable (status=%s)", draft_id, getattr(draft, "status", None))
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": "This draft is no longer pending."},
                )
                return {"status": "stale"}

            if action == "approve_draft":
                draft.status = "approved"
                draft.resolved_at = datetime.utcnow()
                db.add(DirectMessage(
                    conversation_id=conversation_id,
                    sender_id=draft.contractor_id,
                    content=draft.content,
                ))
                await db.commit()
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": f"Approved and sent!\n\n{draft.content}"},
                )
                logger.info("telegram callback: approved draft %s", draft_id)
            else:
                draft.status = "dismissed"
                draft.resolved_at = datetime.utcnow()
                await db.commit()
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/editMessageText",
                    json={"chat_id": chat_id, "message_id": message_id, "text": "Draft dismissed."},
                )
                logger.info("telegram callback: dismissed draft %s", draft_id)

    return {"status": "ok"}


# ─────────────────────────────────────────────
#  WhatsApp Cloud API webhook
# ─────────────────────────────────────────────
def _normalize_phone(value: Optional[str]) -> str:
    return "".join(ch for ch in (value or "")).lstrip("+").replace(" ", "")


@router.get("/whatsapp")
async def whatsapp_verify(
    hub_mode: Optional[str] = None,
    hub_verify_token: Optional[str] = None,
    hub_challenge: Optional[str] = None,
):
    """Meta webhook subscription challenge."""
    if hub_mode == "subscribe" and hub_verify_token == settings.WHATSAPP_VERIFY_TOKEN:
        return Response(content=hub_challenge or "", media_type="text/plain")
    raise HTTPException(status_code=403, detail="Verification failed")


@router.post("/whatsapp")
async def whatsapp_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    """Receive WhatsApp messages. Verifies the Meta signature, then routes any
    inbound text into the user's existing conversation so it shows up in chat."""
    import json
    raw = await request.body()
    sig = request.headers.get("X-Hub-Signature-256")
    secret = settings.WHATSAPP_APP_SECRET or settings.META_APP_SECRET
    if secret:
        from app.services.whatsapp_service import verify_whatsapp_signature
        if not verify_whatsapp_signature(raw, sig):
            raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        data = json.loads(raw or b"{}")
    except Exception:
        return {"status": "ignored"}

    for entry in data.get("entry", []):
        for change in entry.get("value", {}).get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                if msg.get("type") != "text":
                    continue
                wa_id = msg.get("from")
                text = msg.get("text", {}).get("body", "")
                if not wa_id or not text:
                    continue
                # Match the sender to a local user (WhatsApp id or phone).
                user = (await db.exec(
                    select(User).where(User.wa_id == wa_id)
                )).first()
                if not user:
                    norm = _normalize_phone(wa_id)
                    res = await db.exec(select(User))
                    for u in res.all():
                        if u.phone and _normalize_phone(u.phone) == norm:
                            user = u
                            user.wa_id = wa_id
                            db.add(user)
                            break
                if not user:
                    logger.info("whatsapp: no matching user for %s", wa_id)
                    continue
                # Append to the most recent active conversation for this user.
                conv = (await db.exec(
                    select(Conversation)
                    .where((Conversation.customer_id == user.id) | (Conversation.contractor_id == user.id))
                    .where(~Conversation.archived_by_customer)
                    .where(~Conversation.archived_by_contractor)
                    .order_by(Conversation.id.desc())
                )).first()
                if not conv:
                    logger.info("whatsapp: no conversation for user %s", user.id)
                    continue
                db.add(DirectMessage(
                    conversation_id=conv.id,
                    sender_id=user.id,
                    content=f"[WhatsApp] {text}",
                ))
                await db.commit()
                logger.info("whatsapp: routed message from %s to conv %s", wa_id, conv.id)
    return {"status": "ok"}
