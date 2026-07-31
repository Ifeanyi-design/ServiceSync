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
from app.models.all_models import (
    Conversation, DirectMessage, User, OmnichannelIntegration, AIDraft,
    UserBlock, UserReport,
)
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

    def online_user_ids(self, conversation_id: int) -> List[int]:
        """Unique user IDs currently connected to this conversation on this instance."""
        conns = self.active_connections.get(conversation_id) or []
        return list({uid for _, uid in conns})

    def is_user_online(self, conversation_id: int, user_id: int) -> bool:
        return user_id in self.online_user_ids(conversation_id)

    async def broadcast_to_conversation(self, message: str, conversation_id: int, sender_websocket: WebSocket):
        # Hub handles local delivery (no Redis) or cross-instance fanout (Redis).
        # Exclude sender by user_id so multi-instance don't need the websocket object.
        sender_uid = None
        if conversation_id in self.active_connections:
            for connection, uid in self.active_connections[conversation_id]:
                if connection == sender_websocket:
                    sender_uid = uid
                    break
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
            try:
                self.active_connections[conversation_id].remove(d)
            except (ValueError, KeyError):
                pass

    async def broadcast_to_all(self, message: str, conversation_id: int):
        from app.services.broadcast_hub import publish
        await publish(conversation_id, message, exclude_user_id=None)

    async def send_to_user(self, message: str, conversation_id: int, target_user_id: int):
        """Deliver only to a specific user on this instance (e.g. AI drafts)."""
        if conversation_id not in self.active_connections:
            return
        dead = []
        for connection, uid in self.active_connections[conversation_id]:
            if uid != target_user_id:
                continue
            try:
                await connection.send_text(message)
            except Exception:
                dead.append((connection, uid))
        for d in dead:
            try:
                self.active_connections[conversation_id].remove(d)
            except (ValueError, KeyError):
                pass

    async def send_json_to_socket(self, websocket: WebSocket, payload: dict):
        try:
            await websocket.send_text(json.dumps(payload))
        except Exception:
            pass

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
    ai_reasoning: Optional[Dict[str, Any]] = None

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
        matched_contractors=matched_list,
        ai_reasoning={
            "detected_issue": triage_data.get("summary", "Unknown issue"),
            "urgency": triage_data.get("urgency", "Normal"),
            "required_professional": triage_data.get("profession_required", "General"),
            "matches_found": len(matched_list)
        } if ready else None
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
    await db.refresh(new_msg)

    # Broadcast structured message so chat clients render consistently
    payload = json.dumps({
        "type": "message",
        "id": new_msg.id,
        "sender_id": current_user.id,
        "content": clean_content,
        "attachment_url": None,
        "attachment_type": None,
        "attachment_name": None,
        "timestamp": (new_msg.timestamp.isoformat() + "Z") if new_msg.timestamp else datetime.utcnow().isoformat() + "Z",
    })
    await manager.broadcast_to_all(payload, request.conversation_id)
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
_ALLOWED_EXT = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".mp4", ".mov", ".webm", ".ogg", ".pdf", ".doc", ".docx", ".txt"}


@router.post("/upload")
async def upload_chat_media(
    file: UploadFile = File(...),
    current_user: User = Depends(get_current_user),
):
    """Upload an image/video/file for a chat message. Returns a served URL."""
    from pathlib import Path as _Path
    from app.services.upload_service import save_upload
    data = await file.read()
    original_name = (file.filename or "file").strip() or "file"
    try:
        url = await save_upload(
            data, original_name,
            allowlist=_ALLOWED_EXT, max_bytes=10 * 1024 * 1024, folder="chat",
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    ext = _Path(original_name).suffix.lower().lstrip(".") or "file"
    return {
        "url": url,
        "name": original_name,
        "ext": ext,
        "content_type": file.content_type or "",
        "size": len(data),
    }


def _presence_payload(conversation_id: int, user_id: int, online: bool) -> str:
    return json.dumps({
        "type": "presence",
        "user_id": user_id,
        "online": online,
        "online_user_ids": manager.online_user_ids(conversation_id),
    })


@router.websocket("/ws/{conversation_id}")
async def websocket_endpoint(
    websocket: WebSocket, 
    conversation_id: int, 
    token: Optional[str] = Query(None)
):
    from datetime import datetime

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

    # Verify user belongs to the conversation; capture peer id for presence/receipts
    peer_id: Optional[int] = None
    async with async_session_maker() as db:
        result = await db.exec(select(Conversation).where(Conversation.id == conversation_id))
        conversation = result.first()
        if not conversation or user_id not in [conversation.customer_id, conversation.contractor_id]:
            await websocket.close(code=1008, reason="Unauthorized")
            return
        peer_id = (
            conversation.contractor_id
            if user_id == conversation.customer_id
            else conversation.customer_id
        )

    await manager.connect(websocket, conversation_id, user_id)

    # Snapshot of who is online for the newly connected client
    await manager.send_json_to_socket(websocket, {
        "type": "presence",
        "user_id": user_id,
        "online": True,
        "online_user_ids": manager.online_user_ids(conversation_id),
    })
    # Tell peers we came online
    await manager.broadcast_to_conversation(
        _presence_payload(conversation_id, user_id, True),
        conversation_id,
        websocket,
    )

    # Opening the thread = read: advance cursor + notify peer
    try:
        async with async_session_maker() as db:
            conv_result = await db.exec(select(Conversation).where(Conversation.id == conversation_id))
            conv = conv_result.first()
            if conv:
                from app.services.notification_service import mark_conversation_read
                await mark_conversation_read(db, conv, user_id)
        read_evt = json.dumps({
            "type": "read",
            "user_id": user_id,
            "read_at": datetime.utcnow().isoformat() + "Z",
        })
        await manager.broadcast_to_conversation(read_evt, conversation_id, websocket)
    except Exception as e:
        logger.warning("WS initial read mark failed: %s", e)

    try:
        while True:
            data = await websocket.receive_text()

            # Parse control vs chat payloads
            content = data
            attachment_url = None
            attachment_type = None
            attachment_name = None
            control_type = None
            try:
                parsed = json.loads(data)
                if isinstance(parsed, dict):
                    control_type = parsed.get("type")
                    if control_type in ("typing", "read", "presence", "ping"):
                        pass  # control message — handled below
                    else:
                        content = parsed.get("content", "") or ""
                        attachment_url = parsed.get("attachment_url")
                        attachment_type = parsed.get("attachment_type")
                        attachment_name = parsed.get("attachment_name") or None
                        control_type = None  # treat as chat message
            except (json.JSONDecodeError, TypeError, ValueError):
                control_type = None

            # --- Control messages (not persisted) ---
            if control_type == "typing":
                typing_evt = json.dumps({"type": "typing", "user_id": user_id})
                await manager.broadcast_to_conversation(typing_evt, conversation_id, websocket)
                continue

            if control_type == "read":
                try:
                    async with async_session_maker() as db:
                        conv_result = await db.exec(
                            select(Conversation).where(Conversation.id == conversation_id)
                        )
                        conv = conv_result.first()
                        if conv:
                            from app.services.notification_service import mark_conversation_read
                            await mark_conversation_read(db, conv, user_id)
                except Exception as e:
                    logger.warning("WS read mark failed: %s", e)
                read_evt = json.dumps({
                    "type": "read",
                    "user_id": user_id,
                    "read_at": datetime.utcnow().isoformat() + "Z",
                })
                await manager.broadcast_to_conversation(read_evt, conversation_id, websocket)
                continue

            if control_type == "ping":
                await manager.send_json_to_socket(websocket, {"type": "pong"})
                continue

            if control_type == "presence":
                # Clients shouldn't set presence; ignore
                continue

            # Empty chat (no text, no attachment) — ignore
            if not (content or "").strip() and not attachment_url:
                continue

            # Save chat message to DB
            new_msg = None
            async with async_session_maker() as db:
                new_msg = DirectMessage(
                    conversation_id=conversation_id,
                    sender_id=user_id,
                    content=content or "",
                    attachment_url=attachment_url,
                    attachment_type=attachment_type,
                    attachment_name=attachment_name,
                )
                db.add(new_msg)
                await db.commit()
                await db.refresh(new_msg)

            # Structured broadcast so clients get id + original filename
            ts = new_msg.timestamp.isoformat() + "Z" if new_msg.timestamp else datetime.utcnow().isoformat() + "Z"
            msg_payload = {
                "type": "message",
                "id": new_msg.id,
                "sender_id": user_id,
                "content": content or "",
                "attachment_url": attachment_url,
                "attachment_type": attachment_type,
                "attachment_name": attachment_name,
                "timestamp": ts,
            }
            await manager.broadcast_to_conversation(
                json.dumps(msg_payload), conversation_id, websocket
            )

            # Ack sender: delivered if peer currently in this conversation
            peer_online = peer_id is not None and manager.is_user_online(conversation_id, peer_id)
            await manager.send_json_to_socket(websocket, {
                "type": "message_ack",
                "id": new_msg.id,
                "status": "delivered" if peer_online else "sent",
            })

            # AI Autonomy: check if the receiver is a contractor with auto-reply enabled
            async with async_session_maker() as db:
                conv_result = await db.exec(select(Conversation).where(Conversation.id == conversation_id))
                conversation = conv_result.first()
                if not conversation:
                    continue

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
                alert_text = content or (f"[attachment: {attachment_name or attachment_type or 'file'}]")

                # Level 1: manual — send cross-platform alert
                if autonomy == 1:
                    try:
                        customer_result = await db.exec(select(User).where(User.id == customer_id))
                        customer = customer_result.first()
                        customer_name = customer.full_name if customer else "Customer"
                        await alert_new_message(db, contractor_id, customer_name, alert_text)
                    except Exception:
                        pass
                    continue

                contractor_context = {
                    "profession": contractor.profession,
                    "base_pricing": contractor.base_pricing,
                    "service_radius_miles": contractor.service_radius_miles,
                    "working_hours_start": contractor.working_hours_start,
                    "working_hours_end": contractor.working_hours_end,
                    "ai_tone_preference": contractor.ai_tone_preference,
                }

                ai_reply = await generate_contractor_reply(alert_text, contractor_context)

                if autonomy == 2:
                    draft = AIDraft(
                        conversation_id=conversation_id,
                        contractor_id=contractor_id,
                        content=ai_reply,
                        status="pending",
                    )
                    db.add(draft)
                    await db.commit()
                    await db.refresh(draft)

                    draft_msg = json.dumps({
                        "type": "message",
                        "id": None,
                        "sender_id": contractor_id,
                        "content": f"[AI DRAFT:{draft.id}] {ai_reply}",
                        "attachment_url": None,
                        "attachment_type": None,
                        "attachment_name": None,
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "is_draft": True,
                    })
                    await manager.send_to_user(draft_msg, conversation_id, contractor_id)
                    logger.info(
                        "Draft %d created for conversation %d, sent to contractor %d via WS",
                        draft.id, conversation_id, contractor_id,
                    )

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
                    auto_dm = DirectMessage(
                        conversation_id=conversation_id,
                        sender_id=contractor_id,
                        content=ai_reply,
                    )
                    db.add(auto_dm)
                    await db.commit()
                    await db.refresh(auto_dm)
                    auto_payload = json.dumps({
                        "type": "message",
                        "id": auto_dm.id,
                        "sender_id": contractor_id,
                        "content": ai_reply,
                        "attachment_url": None,
                        "attachment_type": None,
                        "attachment_name": None,
                        "timestamp": (auto_dm.timestamp.isoformat() + "Z") if auto_dm.timestamp else datetime.utcnow().isoformat() + "Z",
                    })
                    await manager.broadcast_to_all(auto_payload, conversation_id)

                    audit = AIOperationsAuditLog(
                        action_type="chat_auto_reply",
                        user_id=customer_id,
                        contractor_id=contractor_id,
                        gemini_model_version=settings.GEMINI_MODEL,
                        input_context={"message": alert_text},
                        raw_ai_response=ai_reply,
                        structured_decision={"autonomy_level": 3, "conversation_id": conversation_id},
                        status="success",
                    )
                    db.add(audit)
                    await db.commit()
            
    except WebSocketDisconnect:
        manager.disconnect(websocket, conversation_id)
        # Only announce offline if this user has no remaining sockets in the room
        if not manager.is_user_online(conversation_id, user_id):
            offline_payload = _presence_payload(conversation_id, user_id, False)
            await manager.broadcast_to_all(offline_payload, conversation_id)
    except Exception as e:
        logger.error("WS error conversation=%s user=%s: %s", conversation_id, user_id, e)
        manager.disconnect(websocket, conversation_id)
        if not manager.is_user_online(conversation_id, user_id):
            try:
                await manager.broadcast_to_all(
                    _presence_payload(conversation_id, user_id, False),
                    conversation_id,
                )
            except Exception:
                pass


# ─── Phase 5: inbox hygiene + safety ───────────────────────────────────────

class ConversationPrefsUpdate(BaseModel):
    archived: Optional[bool] = None
    muted: Optional[bool] = None


class ReportBody(BaseModel):
    reason: str = "other"
    details: Optional[str] = None


def _assert_participant(conv: Conversation, user_id: int) -> None:
    if user_id not in (conv.customer_id, conv.contractor_id):
        raise HTTPException(status_code=403, detail="Not a participant")


@router.patch("/conversations/{conversation_id}/prefs")
async def update_conversation_prefs(
    conversation_id: int,
    body: ConversationPrefsUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Archive or mute a conversation for the current user only."""
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _assert_participant(conv, current_user.id)

    is_customer = current_user.id == conv.customer_id
    if body.archived is not None:
        if is_customer:
            conv.archived_by_customer = body.archived
        else:
            conv.archived_by_contractor = body.archived
    if body.muted is not None:
        if is_customer:
            conv.muted_by_customer = body.muted
        else:
            conv.muted_by_contractor = body.muted

    db.add(conv)
    await db.commit()
    await db.refresh(conv)
    return {
        "ok": True,
        "conversation_id": conv.id,
        "archived": conv.archived_by_customer if is_customer else conv.archived_by_contractor,
        "muted": conv.muted_by_customer if is_customer else conv.muted_by_contractor,
    }


@router.post("/conversations/{conversation_id}/block")
async def block_chat_partner(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Block the other participant. Hides their threads from your inbox."""
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _assert_participant(conv, current_user.id)

    blocked_id = conv.contractor_id if current_user.id == conv.customer_id else conv.customer_id
    if blocked_id == current_user.id:
        raise HTTPException(status_code=400, detail="Cannot block yourself")

    existing = (
        await db.exec(
            select(UserBlock).where(
                UserBlock.blocker_id == current_user.id,
                UserBlock.blocked_id == blocked_id,
            )
        )
    ).first()
    if not existing:
        db.add(UserBlock(blocker_id=current_user.id, blocked_id=blocked_id))
        await db.commit()
    return {"ok": True, "blocked_id": blocked_id}


@router.delete("/conversations/{conversation_id}/block")
async def unblock_chat_partner(
    conversation_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _assert_participant(conv, current_user.id)
    blocked_id = conv.contractor_id if current_user.id == conv.customer_id else conv.customer_id
    rows = (
        await db.exec(
            select(UserBlock).where(
                UserBlock.blocker_id == current_user.id,
                UserBlock.blocked_id == blocked_id,
            )
        )
    ).all()
    for r in rows:
        await db.delete(r)
    await db.commit()
    return {"ok": True, "blocked_id": blocked_id}


@router.post("/conversations/{conversation_id}/report")
async def report_chat_partner(
    conversation_id: int,
    body: ReportBody,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Submit a safety report about the other participant."""
    conv = await db.get(Conversation, conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")
    _assert_participant(conv, current_user.id)

    reported_id = conv.contractor_id if current_user.id == conv.customer_id else conv.customer_id
    allowed = {"harassment", "spam", "scam", "unsafe", "other"}
    reason = (body.reason or "other").strip().lower()
    if reason not in allowed:
        reason = "other"
    details = (body.details or "").strip()[:2000] or None

    report = UserReport(
        reporter_id=current_user.id,
        reported_id=reported_id,
        conversation_id=conv.id,
        job_id=conv.job_id,
        reason=reason,
        details=details,
        status="open",
    )
    db.add(report)
    await db.commit()
    await db.refresh(report)
    return {"ok": True, "report_id": report.id}

