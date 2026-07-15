from fastapi import APIRouter, Depends, HTTPException, Request, Response, BackgroundTasks
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import Any
import httpx

from app.api.dependencies import get_db
from app.core.database import async_session_maker
from app.models.all_models import OmnichannelIntegration, User, Conversation, DirectMessage, AIDraft, StripeEvent
from app.core.config import settings
from app.models.audit_log import AIOperationsAuditLog
from app.services.gemini_service import generate_contractor_reply

router = APIRouter()

META_VERIFY_TOKEN = "your_secure_verify_token" 


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

    if hub_mode == "subscribe" and hub_verify_token == META_VERIFY_TOKEN:
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

@router.post("/{platform}")
async def receive_webhook(
    platform: str,
    request: Request,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Handle incoming messages from external messaging platforms.
    """
    payload = await request.json()
    
    sender_id = None
    recipient_id = None
    message_text = None

    # Payload parsers
    if platform == "whatsapp":
        try:
            entry = payload["entry"][0]["changes"][0]["value"]
            message = entry["messages"][0]
            sender_id = message["from"]
            recipient_id = entry["metadata"]["display_phone_number"]
            message_text = message["text"]["body"]
        except (KeyError, IndexError):
            return {"status": "ignored"}
            
    elif platform == "telegram":
        # Handle callback queries from inline keyboard (approve/dismiss draft)
        if "callback_query" in payload:
            callback = payload["callback_query"]
            callback_id = callback.get("id", "")
            data = callback.get("data", "")
            chat_id = str(callback["message"]["chat"]["id"])
            message_id = callback["message"]["message_id"]

            # Find the integration by chat_id to get the bot token
            async with async_session_maker() as db:
                integ_result = await db.exec(
                    select(OmnichannelIntegration).where(
                        OmnichannelIntegration.platform == "telegram",
                        OmnichannelIntegration.platform_account_id == chat_id,
                        OmnichannelIntegration.is_active == True,
                    )
                )
                integ = integ_result.first()

            if not integ:
                return {"status": "no_integration"}

            bot_token = integ.access_token

            # ALWAYS answer the callback query first to stop the spinner
            async with httpx.AsyncClient() as client:
                await client.post(
                    f"https://api.telegram.org/bot{bot_token}/answerCallbackQuery",
                    json={"callback_query_id": callback_id},
                )

                if data.startswith("approve_draft:"):
                    parts = data.split(":")
                    conversation_id = int(parts[1])
                    draft_id = int(parts[2])

                    async with async_session_maker() as db:
                        from datetime import datetime
                        draft_result = await db.exec(select(AIDraft).where(AIDraft.id == draft_id))
                        draft = draft_result.first()
                        if draft and draft.conversation_id == conversation_id and draft.status == "pending":
                            clean_content = draft.content
                            new_msg = DirectMessage(
                                conversation_id=conversation_id,
                                sender_id=draft.contractor_id,
                                content=clean_content,
                            )
                            db.add(new_msg)
                            draft.status = "approved"
                            draft.resolved_at = datetime.utcnow()
                            await db.commit()

                            await client.post(
                                f"https://api.telegram.org/bot{bot_token}/editMessageText",
                                json={
                                    "chat_id": chat_id,
                                    "message_id": message_id,
                                    "text": f"Approved and sent!\n\n{clean_content}",
                                },
                            )

                elif data.startswith("dismiss_draft:"):
                    parts = data.split(":")
                    draft_id = int(parts[2])

                    async with async_session_maker() as db:
                        from datetime import datetime
                        draft_result = await db.exec(select(AIDraft).where(AIDraft.id == draft_id))
                        draft = draft_result.first()
                        if draft and draft.status == "pending":
                            draft.status = "dismissed"
                            draft.resolved_at = datetime.utcnow()
                            await db.commit()

                            await client.post(
                                f"https://api.telegram.org/bot{bot_token}/editMessageText",
                                json={
                                    "chat_id": chat_id,
                                    "message_id": message_id,
                                    "text": "Draft dismissed.",
                                },
                            )

            return {"status": "ok"}

        try:
            message = payload["message"]
            sender_id = str(message["chat"]["id"])
            recipient_id = "telegram_bot" 
            message_text = message["text"]
        except KeyError:
            return {"status": "ignored"}
            
    elif platform == "messenger":
        try:
            entry = payload["entry"][0]["messaging"][0]
            sender_id = entry["sender"]["id"]
            recipient_id = entry["recipient"]["id"]
            message_text = entry["message"]["text"]
        except (KeyError, IndexError):
            return {"status": "ignored"}
            
    else:
        raise HTTPException(status_code=400, detail="Unsupported platform")

    if not sender_id or not recipient_id or not message_text:
        return {"status": "ignored"}

    # Step A: Query Integration & Contractor Profile
    integration_query = select(OmnichannelIntegration).where(
        OmnichannelIntegration.platform == platform,
        OmnichannelIntegration.platform_account_id == recipient_id,
        OmnichannelIntegration.is_active == True
    )
    result = await db.exec(integration_query)
    integration = result.first()
    
    if not integration:
        return {"status": "unrecognized_integration"}

    contractor = await db.get(User, integration.contractor_id)
    if not contractor:
        return {"status": "contractor_not_found"}

    # Step B: Fetch contractor constraints
    contractor_context = {
        "profession": contractor.profession,
        "base_pricing": contractor.base_pricing,
        "service_radius_miles": contractor.service_radius_miles,
        "working_hours_start": contractor.working_hours_start,
        "working_hours_end": contractor.working_hours_end,
        "ai_tone_preference": contractor.ai_tone_preference
    }

    # Step C: Call Gemini
    bot_reply = await generate_contractor_reply(message_text, contractor_context)

    # Step D: Log AIOperationsAuditLog
    structured_decision = {
        "platform": platform,
        "sender": sender_id,
        "recipient": recipient_id,
        "contractor_context_used": contractor_context
    }
    
    audit_log = AIOperationsAuditLog(
        action_type="omnichannel_auto_reply",
        user_id=contractor.id,
        gemini_model_version=settings.GEMINI_MODEL,
        input_context={"incoming_message": message_text, "context": contractor_context},
        raw_ai_response=bot_reply,
        structured_decision=structured_decision,
        status="success"
    )
    db.add(audit_log)
    await db.commit()

    # Step E: Fire outbound message task
    background_tasks.add_task(
        send_outbound_message,
        platform=platform,
        recipient_id=sender_id, # Send back to the user
        text=bot_reply,
        access_token=integration.access_token
    )

    return {"status": "success"}
