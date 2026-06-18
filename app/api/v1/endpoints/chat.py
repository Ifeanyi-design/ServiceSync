from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, WebSocket, WebSocketDisconnect, Query
from sqlmodel.ext.asyncio.session import AsyncSession
from sqlmodel import select
from typing import Any, List, Dict, Optional
from pydantic import BaseModel
import jwt
from jwt.exceptions import InvalidTokenError

from app.api.dependencies import get_db
from app.services.gemini_service import extract_triage_info
from app.services.matching_engine import find_matches
from app.models.audit_log import AIOperationsAuditLog
from app.models.all_models import Conversation, DirectMessage, User
from app.core.config import settings
from app.core.database import async_session_maker

router = APIRouter()

class ConnectionManager:
    def __init__(self):
        # Maps conversation_id -> list of active websockets
        self.active_connections: Dict[int, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, conversation_id: int):
        await websocket.accept()
        if conversation_id not in self.active_connections:
            self.active_connections[conversation_id] = []
        self.active_connections[conversation_id].append(websocket)

    def disconnect(self, websocket: WebSocket, conversation_id: int):
        if conversation_id in self.active_connections:
            if websocket in self.active_connections[conversation_id]:
                self.active_connections[conversation_id].remove(websocket)
            if not self.active_connections[conversation_id]:
                del self.active_connections[conversation_id]

    async def broadcast_to_conversation(self, message: str, conversation_id: int, sender_websocket: WebSocket):
        if conversation_id in self.active_connections:
            for connection in self.active_connections[conversation_id]:
                if connection != sender_websocket:
                    await connection.send_text(message)

manager = ConnectionManager()

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
            "zip_code": triage_data.get("zip_code"),
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

    await manager.connect(websocket, conversation_id)
    try:
        while True:
            data = await websocket.receive_text()
            
            # Save to DB asynchronously
            async with async_session_maker() as db:
                new_msg = DirectMessage(
                    conversation_id=conversation_id,
                    sender_id=user_id,
                    content=data
                )
                db.add(new_msg)
                await db.commit()
                
            # Broadcast to other participant
            await manager.broadcast_to_conversation(data, conversation_id, websocket)
            
    except WebSocketDisconnect:
        manager.disconnect(websocket, conversation_id)
