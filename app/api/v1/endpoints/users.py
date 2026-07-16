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
