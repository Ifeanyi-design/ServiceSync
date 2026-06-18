from fastapi import APIRouter, Depends, HTTPException, Request, Response, BackgroundTasks
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import Any
import httpx

from app.api.dependencies import get_db
from app.models.all_models import OmnichannelIntegration, User
from app.core.config import settings
from app.models.audit_log import AIOperationsAuditLog
from app.services.gemini_service import generate_contractor_reply

router = APIRouter()

META_VERIFY_TOKEN = "your_secure_verify_token" 

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
