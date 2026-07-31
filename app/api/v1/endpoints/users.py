from fastapi import APIRouter, Depends, HTTPException
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import Any

from app.api.dependencies import get_current_user, get_db
from app.models.all_models import User
from app.schemas.user import UserResponse, ContractorProfileUpdate, UserProfileUpdate

router = APIRouter()

@router.get("/me", response_model=UserResponse)
async def read_user_me(current_user: User = Depends(get_current_user)) -> Any:
    """
    Get current user profile.
    """
    return current_user


@router.get("/me/notifications")
async def list_my_notifications(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Real in-app notifications derived from unread messages + job actions."""
    from app.services.notification_service import build_notifications
    return await build_notifications(db, current_user)


@router.post("/me/notifications/read-all")
async def mark_all_notifications_read(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Any:
    """Advance the read cursor on all conversations so the notification badge clears."""
    from sqlmodel import select as sql_select
    from app.models.all_models import ConversationParticipant, Message
    from sqlalchemy import func

    # Find all participants for this user
    parts_result = await db.exec(
        sql_select(ConversationParticipant).where(
            ConversationParticipant.user_id == current_user.id
        )
    )
    participants = parts_result.all()

    for part in participants:
        # Get the latest message id in this conversation
        msg_result = await db.exec(
            sql_select(func.max(Message.id)).where(
                Message.conversation_id == part.conversation_id
            )
        )
        latest_id = msg_result.first()
        if latest_id:
            part.last_read_message_id = latest_id
            db.add(part)

    await db.commit()
    return {"ok": True}


@router.get("/me/profile", response_model=UserResponse)
async def get_user_profile(current_user: User = Depends(get_current_user)) -> Any:
    return current_user

@router.post("/me/profile", response_model=UserResponse)
async def update_user_profile(
    profile_in: UserProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Update profile fields from the contractor integrations settings forms.
    """
    if current_user.role != "contractor":
        raise HTTPException(status_code=403, detail="Only contractors can update these profile fields")
    
    update_data = profile_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(current_user, key, value)
        
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    return current_user

@router.put("/me/profile", response_model=UserResponse)
async def update_contractor_profile(
    profile_in: ContractorProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    """
    Update contractor profile details.
    """
    if current_user.role != "contractor":
        raise HTTPException(status_code=403, detail="Only contractors can update these profile fields")
    
    update_data = profile_in.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(current_user, key, value)
        
    db.add(current_user)
    await db.commit()
    await db.refresh(current_user)
    return current_user

@router.post("/{user_id}/ban")
async def ban_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    
    target.is_active = False
    await db.commit()
    return {"ok": True, "message": f"{target.email} has been banned."}

@router.post("/{user_id}/unban")
async def unban_user(
    user_id: int,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
) -> Any:
    if current_user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin only")
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    
    target.is_active = True
    await db.commit()
    return {"ok": True, "message": f"{target.email} has been unbanned."}
