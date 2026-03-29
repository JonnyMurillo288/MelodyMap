"""
API key authentication + rate limiting middleware for FastAPI.

- Checks X-API-Key header against api_users table (hashed)
- Enforces per-tier rate limits via sliding window
- Passes through internal service calls (Go -> Python) via X-Internal-Secret
- Logs all API usage to api_usage_log table
"""
import os
import hashlib
import secrets
import time
import uuid
from collections import defaultdict
from typing import Optional

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from utils.database import get_pg_conn
from config.config import INTERNAL_SERVICE_SECRET

# Paths that don't require API key auth
PUBLIC_PATHS = {
    "/docs",
    "/openapi.json",
    "/redoc",
    "/health",
    "/metrics",
    "/api/v1/models",
    "/api/v1/health",
    "/api/v1/auth/register",
}

# Legacy paths (keep old auth, don't require API key)
LEGACY_PREFIX = "/ml/"
INTERLUDE_PREFIX = "/interlude/"


# ---------------------------------------------------------------
# In-memory sliding window rate limiter
# For single-instance deployment (Phase 1).
# Phase 2+ can swap to Redis-backed counter.
# ---------------------------------------------------------------
class RateLimiter:
    def __init__(self):
        self._windows: dict[str, list[float]] = defaultdict(list)

    def check(self, user_id: str, limit: int) -> bool:
        now = time.time()
        window = self._windows[user_id]
        # Prune entries older than 1 hour
        window[:] = [t for t in window if now - t < 3600]
        if len(window) >= limit:
            return False
        window.append(now)
        return True

    def remaining(self, user_id: str, limit: int) -> int:
        now = time.time()
        window = self._windows[user_id]
        window[:] = [t for t in window if now - t < 3600]
        return max(0, limit - len(window))


rate_limiter = RateLimiter()


# ---------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------
def _lookup_user_by_key_hash(key_hash: str) -> Optional[dict]:
    """Look up api_users row by hashed API key. Returns dict or None."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute(
            """SELECT user_id, email, org_name, tier, rate_limit_per_hour
               FROM api_users WHERE api_key_hash = %s""",
            (key_hash,),
        )
        row = cur.fetchone()
        conn.close()
        if row:
            return {
                "user_id": str(row[0]),
                "email": row[1],
                "org_name": row[2],
                "tier": row[3],
                "rate_limit_per_hour": row[4],
            }
        return None
    except Exception as e:
        print(f"[auth] DB lookup error: {e}")
        return None


def _log_usage(user_id: str, endpoint: str, method: str, status_code: int, latency_ms: float):
    """Fire-and-forget usage logging."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO api_usage_log (user_id, endpoint, method, status_code, latency_ms)
               VALUES (%s::uuid, %s, %s, %s, %s)""",
            (user_id, endpoint, method, status_code, latency_ms),
        )
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"[auth] Usage log error (non-fatal): {e}")


def _update_last_active(user_id: str):
    """Update last_active timestamp."""
    try:
        conn = get_pg_conn()
        cur = conn.cursor()
        cur.execute(
            "UPDATE api_users SET last_active = NOW() WHERE user_id = %s::uuid",
            (user_id,),
        )
        conn.commit()
        conn.close()
    except Exception:
        pass


# ---------------------------------------------------------------
# Registration helper (used by the register endpoint)
# ---------------------------------------------------------------
def register_api_user(email: str, org_name: str = None) -> dict:
    """Create a new free-tier API user. Returns the raw API key (shown once)."""
    api_key = secrets.token_urlsafe(32)
    key_hash = hashlib.sha256(api_key.encode()).hexdigest()

    conn = get_pg_conn()
    cur = conn.cursor()
    try:
        cur.execute(
            """INSERT INTO api_users (email, org_name, tier, api_key_hash, rate_limit_per_hour)
               VALUES (%s, %s, 'free', %s, 100)
               RETURNING user_id""",
            (email, org_name, key_hash),
        )
        conn.commit()
    except Exception as e:
        conn.rollback()
        conn.close()
        if "unique" in str(e).lower():
            raise HTTPException(status_code=409, detail="Email already registered")
        raise HTTPException(status_code=500, detail=f"Registration failed: {e}")

    conn.close()
    return {
        "api_key": api_key,
        "tier": "free",
        "rate_limit_per_hour": 100,
    }


# ---------------------------------------------------------------
# Middleware
# ---------------------------------------------------------------
class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        request_id = str(uuid.uuid4())

        # Public paths - no auth
        if path in PUBLIC_PATHS:
            request.state.request_id = request_id
            request.state.user = None
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

        # Legacy endpoints keep their existing auth flow
        if path.startswith(LEGACY_PREFIX) or path.startswith(INTERLUDE_PREFIX):
            request.state.request_id = request_id
            request.state.user = None
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

        # Internal service-to-service (Go -> Python)
        internal_key = request.headers.get("X-Internal-Secret", "")
        if INTERNAL_SERVICE_SECRET and internal_key == INTERNAL_SERVICE_SECRET:
            request.state.request_id = request_id
            request.state.user = {"tier": "internal", "user_id": "internal"}
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

        # API key auth for /api/v1/* endpoints
        if not path.startswith("/api/"):
            # Non-API paths pass through
            request.state.request_id = request_id
            request.state.user = None
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

        api_key = request.headers.get("X-API-Key", "")
        if not api_key:
            raise HTTPException(
                status_code=401,
                detail="Missing X-API-Key header. Register at POST /api/v1/auth/register",
            )

        key_hash = hashlib.sha256(api_key.encode()).hexdigest()
        user = _lookup_user_by_key_hash(key_hash)
        if not user:
            raise HTTPException(status_code=401, detail="Invalid API key")

        # Rate limit
        if not rate_limiter.check(user["user_id"], user["rate_limit_per_hour"]):
            remaining = rate_limiter.remaining(user["user_id"], user["rate_limit_per_hour"])
            raise HTTPException(
                status_code=429,
                detail=f"Rate limit exceeded. Limit: {user['rate_limit_per_hour']}/hr. "
                       f"Upgrade tier for higher limits.",
                headers={
                    "X-RateLimit-Remaining": str(remaining),
                    "X-RateLimit-Limit": str(user["rate_limit_per_hour"]),
                    "Retry-After": "60",
                },
            )

        request.state.user = user
        request.state.request_id = request_id

        start = time.time()
        response = await call_next(request)
        latency = (time.time() - start) * 1000

        # Set rate limit headers
        remaining = rate_limiter.remaining(user["user_id"], user["rate_limit_per_hour"])
        response.headers["X-RateLimit-Limit"] = str(user["rate_limit_per_hour"])
        response.headers["X-RateLimit-Remaining"] = str(remaining)
        response.headers["X-Request-ID"] = request_id

        # Log usage (fire-and-forget)
        _log_usage(user["user_id"], path, request.method, response.status_code, latency)
        _update_last_active(user["user_id"])

        return response
