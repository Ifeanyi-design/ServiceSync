from fastapi import APIRouter
from app.api.v1.endpoints import auth, users, chat, jobs, webhooks, escrow, ai_features, voice, cctv, tools, suppliers

api_router = APIRouter()
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(chat.router, prefix="/chat", tags=["chat"])
api_router.include_router(jobs.router, prefix="/jobs", tags=["jobs"])
api_router.include_router(escrow.router, prefix="/escrow", tags=["escrow"])
api_router.include_router(ai_features.router, prefix="/ai", tags=["ai"])
api_router.include_router(voice.router, prefix="/voice", tags=["voice"])
api_router.include_router(cctv.router, prefix="/cctv", tags=["cctv"])
api_router.include_router(tools.router, prefix="/tools", tags=["tools"])
api_router.include_router(suppliers.router, prefix="/suppliers", tags=["suppliers"])
api_router.include_router(webhooks.router, prefix="/webhooks", tags=["webhooks"])
