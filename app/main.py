from contextlib import asynccontextmanager

import logging
import sys
import time
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
    # Bring the schema in sync (add any missing tables/columns) on every boot so
    # deploys are safe even when the DB was created before new models landed.
    try:
        from app.core.migrate import run_migration
        await run_migration()
    except Exception as exc:  # migration must never block startup
        print(f"WARNING: startup migration failed: {exc}")
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
            "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com https://cdn.tailwindcss.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "script-src 'self' 'unsafe-inline' https://cdn.tailwindcss.com https://js.stripe.com https://*.stripe.com https://js.paystack.co https://*.paystack.co https://*.paystack.com; "
            "connect-src 'self' https://*.stripe.com https://api.stripe.com https://api.paystack.co https://generativelanguage.googleapis.com https://*.cloudinary.com https://api.twilio.com https://graph.facebook.com; "
            "frame-src 'self' https://*.stripe.com https://*.paystack.co https://*.paystack.com https://checkout.paystack.com;",
        )
        # HSTS only makes sense behind TLS; Render terminates HTTPS at the edge.
        if request.url.scheme == "https":
            response.headers.setdefault(
                "Strict-Transport-Security", "max-age=31536000; includeSubDomains"
            )
        return response


app.add_middleware(SecurityHeadersMiddleware)


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Per-IP rate limiter for abuse- and cost-prone endpoints.

    Uses Redis (fixed-window counters) when ``REDIS_URL`` is configured so the
    limit is shared across all instances; otherwise it falls back to an
    in-process in-memory window (fine for a single Render instance).

    Static assets, the health probe, and webhooks (which must stay open for
    Stripe/Meta) are exempt.
    """

    # Exact path -> (max requests, window seconds)
    PROTECTED = {
        # API auth
        "/api/v1/auth/login": (10, 60),
        "/api/v1/auth/signup": (5, 60),
        "/api/v1/auth/forgot-password": (5, 60),
        "/api/v1/auth/reset-password": (5, 60),
        "/api/v1/auth/2fa/verify": (10, 60),
        "/api/v1/chat/triage": (20, 60),
        # Web (server-rendered) auth — same brute-force surface as the API
        "/auth/login": (10, 60),
        "/auth/signup": (5, 60),
        "/auth/forgot-password": (5, 60),
        "/auth/reset-password": (5, 60),
        "/auth/2fa": (10, 60),
    }
    # Path prefix -> (max requests, window seconds). Covers routes with dynamic
    # IDs (escrow funding/release, AI calls, admin ops) that exact matching misses.
    PROTECTED_PREFIXES = {
        "/api/v1/escrow/": (15, 60),   # blocks payment spam / duplicate-charge probing
        "/api/v1/ai/": (30, 60),       # caps Gemini spend per IP
        "/api/v1/jobs/": (40, 60),     # general job/action abuse
        "/admin": (30, 60),            # admin ops
    }
    EXEMPT_PREFIXES = ("/static", "/health", "/api/v1/webhooks")

    _hits: dict = {}
    _redis = None
    _redis_tried = False

    def _get_redis(self):
        if self._redis_tried:
            return self._redis
        self._redis_tried = True
        if not settings.REDIS_URL:
            return None
        try:
            import redis.asyncio as aioredis
            self._redis = aioredis.from_url(settings.REDIS_URL, decode_responses=True)
        except Exception:
            self._redis = None
        return self._redis

    def _limit_for(self, path: str):
        if path in self.PROTECTED:
            return self.PROTECTED[path]
        for pfx, lim in self.PROTECTED_PREFIXES.items():
            if path.startswith(pfx):
                return lim
        return None

    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if any(path.startswith(p) for p in self.EXEMPT_PREFIXES):
            return await call_next(request)
        limit = self._limit_for(path)
        if not limit:
            return await call_next(request)

        max_hits, window = limit
        ip = request.client.host if request.client else "unknown"
        now = time.time()

        redis = self._get_redis()
        if redis is not None:
            # Shared fixed-window counter: INCR, set expiry on first hit.
            key = f"rl:{ip}:{path}"
            try:
                count = await redis.incr(key)
                if count == 1:
                    await redis.expire(key, window)
                if count > max_hits:
                    return Response("Too many requests", status_code=429)
                return await call_next(request)
            except Exception:
                # Redis hiccup must not break requests — fall through to memory.
                pass

        # In-memory fallback (single instance).
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
