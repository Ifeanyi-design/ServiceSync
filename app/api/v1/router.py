from fastapi import APIRouter
from app.api.v1.endpoints import auth, users, chat, jobs, webhooks

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
