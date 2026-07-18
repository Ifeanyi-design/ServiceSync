from contextlib import asynccontextmanager

import logging
import sys
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    stream=sys.stdout,
)

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
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


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Adds baseline security headers and (optionally) enforces HTTPS upstream."""

    async def dispatch(self, request: Request, call_next):
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; "
            "img-src 'self' https: data:; "
            "media-src 'self' https:; "
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "script-src 'self' https://cdn.tailwindcss.com https://js.stripe.com 'unsafe-inline'; "
            "connect-src 'self' https://api.stripe.com https://generativelanguage.googleapis.com",
        )
        # HSTS only makes sense behind TLS; Render terminates HTTPS at the edge.
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


app.add_middleware(SecurityHeadersMiddleware)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Small in-memory per-IP rate limiter for abuse-prone endpoints.

    Shared per-process only — sufficient for a single Render instance. For
    multi-instance production, back this with Redis. Exempts static assets,
    health checks, and webhooks (which must remain open for Stripe/Meta).
    """

    # path -> (max requests, window seconds)
    PROTECTED = {
        "/auth/login": (10, 60),
        "/auth/signup": (5, 60),
        "/api/v1/auth/login": (10, 60),
        "/api/v1/auth/signup": (5, 60),
        "/api/v1/chat/triage": (20, 60),
    }
    EXEMPT_PREFIXES = ("/static", "/health", "/api/v1/webhooks")

    _hits: dict = {}

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return await call_next(request)
        limit = self.PROTECTED.get(path)
        if not limit:
            return await call_next(request)

        max_hits, window = limit
        ip = request.client.host if request.client else "unknown"
        now = time.time()
        key = f"{ip}:{path}"
        dq = self._hits.setdefault(key, [])
        while dq and dq[0] <= now - window:
            dq.pop(0)
        if len(dq) >= max_hits:
            return Response("Too many requests", status_code=429)
        dq.append(now)
        return await call_next(request)


app.add_middleware(RateLimitMiddleware)


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
