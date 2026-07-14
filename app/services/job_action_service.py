"""Job lifecycle action log (Phase 9)."""
from sqlmodel.ext.asyncio.session import AsyncSession

from app.models.all_models import JobAction


async def log_job_action(
    db: AsyncSession,
    job_id: int,
    actor_id: int,
    action: str,
    note: str | None = None,
) -> JobAction:
    action_row = JobAction(job_id=job_id, actor_id=actor_id, action=action, note=note)
    db.add(action_row)
    await db.commit()
    await db.refresh(action_row)
    return action_row
