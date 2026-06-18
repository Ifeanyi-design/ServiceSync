from fastapi import Depends, HTTPException, status, Request
from fastapi.security import OAuth2PasswordBearer
import jwt
from jwt.exceptions import InvalidTokenError
from sqlmodel import select
from sqlmodel.ext.asyncio.session import AsyncSession
from typing import AsyncGenerator, Optional

from app.core.config import settings
from app.core.database import async_session_maker
from app.models.all_models import User

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login", auto_error=False)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_maker() as session:
        yield session

async def get_current_user_optional(
    request: Request, db: AsyncSession = Depends(get_db), token: str = Depends(oauth2_scheme)
) -> Optional[User]:
    # Check cookie if token not in header
    if not token:
        token = request.cookies.get("access_token")
    
    if not token:
        return None

    try:
        payload = jwt.decode(
            token, settings.SECRET_KEY, algorithms=[settings.ALGORITHM]
        )
        user_id: str = payload.get("sub")
        if user_id is None:
            return None
    except InvalidTokenError:
        return None
    
    result = await db.exec(select(User).where(User.id == int(user_id)))
    return result.first()

async def get_current_user(
    current_user: Optional[User] = Depends(get_current_user_optional)
) -> User:
    if not current_user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Could not validate credentials")
    return current_user
