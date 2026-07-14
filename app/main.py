from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from pathlib import Path

from app.core.config import settings
from app.api.v1.router import api_router
from app.web.pages import router as web_router
from app.web.auth_pages import router as auth_web_router
from app.services.broadcast_hub import startup as broadcast_startup, shutdown as broadcast_shutdown


@asynccontextmanager
async def lifespan(app: FastAPI):
    await broadcast_startup()
    yield
    await broadcast_shutdown()


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json",
    lifespan=lifespan,
)

# Mount static files (create the dir so it's always available for uploads)
static_dir = Path(__file__).resolve().parent / "static"
(static_dir / "uploads").mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

# API routes
app.include_router(api_router, prefix=settings.API_V1_STR)

# Web / HTML page routes
app.include_router(auth_web_router)
app.include_router(web_router)


@app.get("/health", tags=["health"])
async def health():
    """Liveness/readiness probe for hosting platforms (e.g. Render)."""
    return {"status": "ok", "service": settings.PROJECT_NAME, "version": settings.VERSION}
