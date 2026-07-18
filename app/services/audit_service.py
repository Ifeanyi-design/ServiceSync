"""Generic, non-AI audit logging.

Reuses the existing ``AIOperationsAuditLog`` table so we get an audit trail for
auth, admin, and escrow actions (not just AI calls) without a new migration.
All writes are best-effort: a logging failure must never break the request.
"""
from datetime import datetime
from typing import Optional

from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.audit_log import AIOperationsAuditLog


async def log_audit(
    db: AsyncSession,
    action_type: str,
    *,
    user_id: Optional[int] = None,
    contractor_id: Optional[int] = None,
    job_id: Optional[int] = None,
    status: str = "success",
    detail: str = "",
) -> None:
    """Append an audit record. Swallows all errors by design."""
    try:
        db.add(AIOperationsAuditLog(
            action_type=action_type,
            user_id=user_id,
            contractor_id=contractor_id,
            job_id=job_id,
            status=status,
            raw_ai_response=detail,
            timestamp=datetime.utcnow(),
        ))
        await db.flush()
    except Exception:
        pass
