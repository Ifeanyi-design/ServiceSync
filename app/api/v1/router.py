from fastapi import APIRouter
from app.api.v1.endpoints import auth, users, chat, jobs, webhooks, escrow, ai_features

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(escrow.router, prefix="/escrow", tags=["escrow"])
api_router.include_router(ai_features.router, prefix="/ai", tags=["ai"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
