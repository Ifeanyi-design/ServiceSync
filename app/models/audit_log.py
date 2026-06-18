from sqlmodel import SQLModel, Field
from typing import Optional, Dict, Any
from datetime import datetime
from sqlalchemy.dialects.postgresql import JSONB
from app.core.config import settings
from sqlalchemy import Column

class AIOperationsAuditLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    timestamp: datetime = Field(default_factory=datetime.utcnow, index=True)
    
    # Context
    action_type: str = Field(index=True) 
    
    job_id: Optional[int] = Field(default=None, foreign_key="job.id")
    user_id: Optional[int] = Field(default=None, foreign_key="user.id")
    contractor_id: Optional[int] = Field(default=None, foreign_key="user.id")
    
    # The AI Data
    gemini_model_version: str = Field(default=settings.GEMINI_MODEL)
    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    latency_ms: Optional[int] = None
    
    # Detailed Payloads (Using PostgreSQL JSONB for queryability)
    input_context: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB)) 
    raw_ai_response: str 
    structured_decision: Dict[str, Any] = Field(default_factory=dict, sa_column=Column(JSONB))
    
    status: str = Field(default="success") # "success", "fallback_triggered", "error"
