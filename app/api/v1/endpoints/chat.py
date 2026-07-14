from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, Query, UploadFile, File
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import Any, List, Dict, Optional
from pydantic import BaseModel
import json
import jwt
import os
import uuid
from pathlib import Path
from jwt.exceptions import InvalidTokenError

from app.api.dependencies import get_db, get_current_user
from app.services.gemini_service import extract_triage_info, generate_contractor_reply
from app.services.matching_engine import find_matches
from app.services.alert_service import alert_new_message
from app.models.audit_log import AIOperationsAuditLog
from app.models.all_models import Conversation, DirectMessage, User, OmnichannelIntegration, AIDraft
from app.core.database import async_session_maker
import logging

logger = logging.getLogger(__name__)
from app.core.config import settings
from app.core.database import async_session_maker

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        # Maps conversation_id -> list of (websocket, user_id) tuples
        self.active_connections: Dict[int, List[tuple]] = {}

    async def connect(self, websocket: WebSocket, conversation_id: int, user_id: int):
        await websocket.accept()
        if conversation_id not in self.active_connections:
            self.active_connections[conversation_id] = []
        self.active_connections[conversation_id].append((websocket, user_id))

    def disconnect(self, websocket: WebSocket, conversation_id: int):
        if conversation_id in self.active_connections:
            self.active_connections[conversation_id] = [
                (ws, uid) for ws, uid in self.active_connections[conversation_id]
                if ws != websocket
            ]
            if not self.active_connections[conversation_id]:
                del self.active_connections[conversation_id]

    async def broadcast_to_conversation(self, message: str, conversation_id: int, sender_websocket: WebSocket):
        # Fan out locally, then to other instances via the hub. We exclude the
        # sender by user_id so we don't need the (per-connection) websocket object
        # once the message crosses an instance boundary.
        sender_uid = None
        if conversation_id in self.active_connections:
            for connection, uid in self.active_connections[conversation_id]:
                if connection == sender_websocket:
                    sender_uid = uid
                    break
        await self._deliver(conversation_id, message, sender_uid)
        from app.services.broadcast_hub import publish
        await publish(conversation_id, message, exclude_user_id=sender_uid)

    async def _deliver(self, conversation_id: int, message: str, exclude_user_id: Optional[int] = None):
        """Send to all local WebSocket connections for a conversation (except one)."""
        if conversation_id not in self.active_connections:
            return
        dead = []
        for connection, uid in self.active_connections[conversation_id]:
            if exclude_user_id is not None and uid == exclude_user_id:
                continue
            try:
                await connection.send_text(message)
            except Exception:
                dead.append((connection, uid))
        for d in dead:
            self.active_connections[conversation_id].remove(d)

    async def broadcast_to_all(self, message: str, conversation_id: int):
        await self._deliver(conversation_id, message)

    async def send_to_user(self, message: str, conversation_id: int, target_user_id: int):
        await self._deliver(conversation_id, message, exclude_user_id=None)
        # send_to_user is intentionally local-only: a single-user target is almost
        # always the connected contractor on this instance (e.g. AI drafts).

manager = ConnectionManager()
from app.services.broadcast_hub import register_local_deliverer
register_local_deliverer(manager._deliver)

def _get_websocket_token(websocket: WebSocket, query_token: Optional[str]) -> Optional[str]:
    if query_token and query_token.lower() != "null":
        return query_token
    
    headers = dict(websocket.scope.get("headers", []))
    cookie_header = headers.get(b"cookie", b"").decode("utf-8", errors="ignore")
    for cookie in cookie_header.split(";"):
        key, _, value = cookie.strip().partition("=")
        if key == "access_token":
            return value
    return None

class ChatMessage(BaseModel):
    role: str # "user" or "bot"
    content: str

class TriageRequest(BaseModel):
    session_id: str
    history: List[ChatMessage]

class TriageResponse(BaseModel):
    bot_reply: str
    ready_for_match: bool
    matched_contractors: list = []

@router.post("/triage", response_model=TriageResponse)
async def chat_triage(
    request: TriageRequest, 
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db)
) -> Any:
    # 1. Extract triage info using Gemini
    history_dict = [msg.model_dump() for msg in request.history]
    triage_data, metadata = await extract_triage_info(history_dict)
    
    bot_reply = triage_data.get("bot_reply", "I'm processing your request.")
    ready = triage_data.get("ready_for_match", False)
    
    matched_list = []
    rejected_list = []
    
    if ready:
        # 2. Run matching engine
        prof = triage_data.get("profession_required")
        location = {
            "zip_code": triage_data.get("postal_code"),
            "country": triage_data.get("country"),
            "state_or_province": triage_data.get("state_or_province"),
            "city": triage_data.get("city"),
            "area": triage_data.get("area"),
            "postal_code": triage_data.get("postal_code"),
            "latitude": triage_data.get("latitude"),
            "longitude": triage_data.get("longitude"),
        }
        
        matches = await find_matches(db, prof, location)
        matched_list = matches["matched"]
        rejected_list = matches["rejected"]

        # Surface verification tier + reputation as trust anchors in the AI reply
        if matched_list:
            top = matched_list[0]
            tier = (top.get("verification_level") or "").strip()
            rep = top.get("reputation_score")
            anchors = []
            if tier and tier.lower() != "none":
                anchors.append(f"{tier} verified")
            if rep:
                anchors.append(f"{rep}% reputation")
            if anchors:
                bot_reply = (
                    f"{bot_reply}\n\nTop match: {top.get('full_name')} "
                    f"({', '.join(anchors)}) — you're protected by escrow on every booking."
                )

    # 3. Write Audit Log
    structured_decision = {
        "triage_extraction": triage_data,
        "matching_results": {
            "matched": matched_list,
            "rejected": rejected_list
        } if ready else None
    }
    
    audit_entry = AIOperationsAuditLog(
        action_type="triage_and_match",
        gemini_model_version=settings.GEMINI_MODEL,
        prompt_tokens=metadata.get("prompt_tokens"),
        completion_tokens=metadata.get("completion_tokens"),
        latency_ms=metadata.get("latency_ms"),
        input_context={"history": history_dict},
        raw_ai_response=metadata.get("raw_response", ""),
        structured_decision=structured_decision,
        status="success"
    )
    db.add(audit_entry)
    await db.commit()

    return TriageResponse(
        bot_reply=bot_reply,
        ready_for_match=ready,
        matched_contractors=matched_list
    )


class ApproveDraftRequest(BaseModel):
    conversation_id: int
    draft_id: int


@router.post("/approve-draft")
async def approve_draft(
    request: ApproveDraftRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Contractor approves an AI draft — saves to DB and sends it as their own message."""
    if current_user.role != "contractor":
        raise HTTPException(status_code=403, detail="Only contractors can approve drafts")

    conv_result = await db.exec(select(Conversation).where(Conversation.id == request.conversation_id))
    conversation = conv_result.first()
    if not conversation or conversation.contractor_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not authorized")

    # Retrieve draft from DB
    from datetime import datetime
    draft_result = await db.exec(select(AIDraft).where(AIDraft.id == request.draft_id))
    draft = draft_result.first()
    if not draft or draft.conversation_id != request.conversation_id or draft.status != "pending":
        raise HTTPException(status_code=404, detail="Draft not found or already handled")

    clean_content = draft.content

    new_msg = DirectMessage(
        conversation_id=request.conversation_id,
        sender_id=current_user.id,
        content=clean_content,
    )
    db.add(new_msg)

    # Mark draft as approved
    draft.status = "approved"
    draft.resolved_at = datetime.utcnow()
    await db.commit()

    # Broadcast to all in conversation (now customer can see the approved message)
    await manager.broadcast_to_all(clean_content, request.conversation_id)
    logger.info("Draft %d approved by contractor %d", draft.id, current_user.id)

    return {"status": "sent", "content": clean_content}


class DismissDraftRequest(BaseModel):
    conversation_id: int
    draft_id: int


@router.post("/dismiss-draft")
async def dismiss_draft(
    request: DismissDraftRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Contractor dismisses an AI draft."""
    if current_user.role != "contractor":
        raise HTTPException(status_code=403, detail="Only contractors can dismiss drafts")

    from datetime import datetime
    draft_result = await db.exec(select(AIDraft).where(AIDraft.id == request.draft_id))
    draft = draft_result.first()
    if not draft or draft.conversation_id != request.conversation_id or draft.status != "pending":
        raise HTTPException(status_code=404, detail="Draft not found or already handled")

    draft.status = "dismissed"
    draft.resolved_at = datetime.utcnow()
    await db.commit()

    return {"status": "dismissed"}


UPLOAD_DIR = Path(__file__).resolve().parent.parent.parent.parent / "static" / "uploads"
_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".pdf", ".doc", ".docx", ".txt"}


@router.post("/upload")
async def upload_chat_media(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Upload an image/video/file for a chat message. Returns a served URL."""
    from app.services.upload_service import save_upload
    data = await file.read()
    try:
        url = await save_upload(
            data, file.filename or "file",
            allowlist=_ALLOWED_EXT, max_bytes=10 * 1024 * 1024, folder="chat",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"url": url, "name": file.filename}


@router.websocket("/ws/{conversation_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    conversation_id: int, 
    token: Optional[str] = Query(None)
):
    token = _get_websocket_token(websocket, token)
    if not token:
        await websocket.close(code=1008, reason="Missing token")
        return

    # Authenticate token and get user manually since Depends() in websockets works differently
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM])
        user_id = int(payload.get("sub"))
    except (InvalidTokenError, ValueError, TypeError):
        await websocket.close(code=1008, reason="Invalid token")
        return

    # Verify user belongs to the conversation
    async with async_session_maker() as db:
        result = await db.exec(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.first()
        if not conversation or user_id not in [conversation.customer_id, conversation.contractor_id]:
            await websocket.close(code=1008, reason="Unauthorized")
            return

    await manager.connect(websocket, conversation_id, user_id)
    try:
        while True:
            data = await websocket.receive_text()

            # Support JSON messages carrying an attachment
            content = data
            attachment_url = None
            attachment_type = None
            try:
                parsed = json.loads(data)
                if isinstance(parsed, dict):
                    content = parsed.get("content", "")
                    attachment_url = parsed.get("attachment_url")
                    attachment_type = parsed.get("attachment_type")
            except (json.JSONDecodeError, TypeError, ValueError):
                pass

            # Save to DB asynchronously
            async with async_session_maker() as db:
                new_msg = DirectMessage(
                    conversation_id=conversation_id,
                    sender_id=user_id,
                    content=content,
                    attachment_url=attachment_url,
                    attachment_type=attachment_type,
                )
                db.add(new_msg)
                await db.commit()
                
            # Broadcast to other participant
            await manager.broadcast_to_conversation(data, conversation_id, websocket)

            # AI Autonomy: check if the receiver is a contractor with auto-reply enabled
            async with async_session_maker() as db:
                conv_result = await db.exec(select(Conversation).where(Conversation.id == conversation_id))
                conversation = conv_result.first()
                if not conversation:
                    continue

                # Determine who the contractor is
                contractor_id = conversation.contractor_id
                customer_id = conversation.customer_id

                # Only trigger AI when the CUSTOMER sends a message
                if user_id != customer_id:
                    continue

                contractor_result = await db.exec(select(User).where(User.id == contractor_id))
                contractor = contractor_result.first()
                if not contractor:
                    continue

                autonomy = contractor.ai_autonomy_level or 1

                # Level 1: manual — send cross-platform alert
                if autonomy == 1:
                    try:
                        customer_result = await db.exec(select(User).where(User.id == customer_id))
                        customer = customer_result.first()
                        customer_name = customer.full_name if customer else "Customer"
                        await alert_new_message(db, contractor_id, customer_name, data)
                    except Exception:
                        pass
                    continue

                # Build contractor context for AI
                contractor_context = {
                    "profession": contractor.profession,
                    "base_pricing": contractor.base_pricing,
                    "service_radius_miles": contractor.service_radius_miles,
                    "working_hours_start": contractor.working_hours_start,
                    "working_hours_end": contractor.working_hours_end,
                    "ai_tone_preference": contractor.ai_tone_preference,
                }

                # Generate AI reply
                ai_reply = await generate_contractor_reply(data, contractor_context)

                if autonomy == 2:
                    # Level 2: AI Draft — save to DB, send to contractor only
                    draft = AIDraft(
                        conversation_id=conversation_id,
                        contractor_id=contractor_id,
                        content=ai_reply,
                        status="pending",
                    )
                    db.add(draft)
                    await db.commit()
                    await db.refresh(draft)

                    draft_msg = f"[AI DRAFT:{draft.id}] {ai_reply}"
                    # Only send draft to the contractor, NOT the customer
                    await manager.send_to_user(draft_msg, conversation_id, contractor_id)
                    logger.info("Draft %d created for conversation %d, sent to contractor %d via WS", draft.id, conversation_id, contractor_id)

                    # Send to Telegram with inline keyboard
                    try:
                        async with async_session_maker() as tg_db:
                            tg_result = await tg_db.exec(
                                select(OmnichannelIntegration).where(
                                    OmnichannelIntegration.contractor_id == contractor_id,
                                    OmnichannelIntegration.platform == "telegram",
                                    OmnichannelIntegration.is_active == True,
                                )
                            )
                            tg_integration = tg_result.first()
                            if tg_integration:
                                import httpx
                                inline_keyboard = {
                                    "inline_keyboard": [
                                        [
                                            {"text": "✅ Approve", "callback_data": f"approve_draft:{conversation_id}:{draft.id}"},
                                            {"text": "❌ Dismiss", "callback_data": f"dismiss_draft:{conversation_id}:{draft.id}"},
                                        ],
                                    ]
                                }
                                telegram_text = (
                                    f"🤖 AI Draft — Job #{conversation_id}\n\n"
                                    f"{ai_reply}\n\n"
                                    f"Tap Approve to send, or Dismiss to discard."
                                )
                                async with httpx.AsyncClient() as client:
                                    resp = await client.post(
                                        f"https://api.telegram.org/bot{tg_integration.access_token}/sendMessage",
                                        json={
                                            "chat_id": tg_integration.platform_account_id,
                                            "text": telegram_text,
                                            "reply_markup": inline_keyboard,
                                        },
                                    )
                                    resp_data = resp.json()
                                    if resp_data.get("ok"):
                                        logger.info("Telegram draft sent to chat_id=%s", tg_integration.platform_account_id)
                                    else:
                                        logger.error("Telegram send failed: %s", resp_data)
                            else:
                                logger.warning("No active Telegram integration for contractor %d", contractor_id)
                    except Exception as e:
                        logger.error("Telegram draft send error: %s", str(e))

                elif autonomy == 3:
                    # Level 3: Auto-Reply — send as the contractor
                    auto_dm = DirectMessage(
                        conversation_id=conversation_id,
                        sender_id=contractor_id,
                        content=ai_reply,
                    )
                    db.add(auto_dm)
                    await db.commit()
                    await manager.broadcast_to_all(ai_reply, conversation_id)

                    # Log the auto-reply
                    audit = AIOperationsAuditLog(
                        action_type="chat_auto_reply",
                        user_id=customer_id,
                        contractor_id=contractor_id,
                        gemini_model_version=settings.GEMINI_MODEL,
                        input_context={"message": data},
                        raw_ai_response=ai_reply,
                        structured_decision={"autonomy_level": 3, "conversation_id": conversation_id},
                        status="success",
                    )
                    db.add(audit)
                    await db.commit()
            
    except WebSocketDisconnect:
        manager.disconnect(websocket, conversation_id)
