"""Small, dependency-free baseline security controls for the FastAPI app.

Rate limits are process-local. For multi-worker or multi-instance production,
use a shared gateway/Redis limiter instead of relying on this in-memory store.
"""
from __future__ import annotations

import os
import threading
import time
import uuid
from collections import defaultdict, deque
from typing import Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware


class _WindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[tuple[str, str], deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def allow(self, key: tuple[str, str], limit: int, window_seconds: int) -> tuple[bool, int]:
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            hits = self._hits[key]
            while hits and hits[0] <= cutoff:
                hits.popleft()
            if len(hits) >= limit:
                retry_after = max(1, int(window_seconds - (now - hits[0])))
                return False, retry_after
            hits.append(now)

            # Bound stale-key growth for long-running processes.
            if len(self._hits) > 10_000:
                for old_key in list(self._hits.keys())[:2_000]:
                    old_hits = self._hits[old_key]
                    while old_hits and old_hits[0] <= cutoff:
                        old_hits.popleft()
                    if not old_hits:
                        self._hits.pop(old_key, None)
        return True, 0


class SecurityControlsMiddleware(BaseHTTPMiddleware):
    """Apply basic route-specific rate limits and standard response headers."""

    def __init__(self, app, *, app_env: str = "development") -> None:
        super().__init__(app)
        self.app_env = app_env.lower()
        self.limiter = _WindowLimiter()
        # Values are deliberately conservative defaults; tune using measured traffic.
        self.rules = {
            ("POST", "/auth/login"): (5, 60),
            ("POST", "/voice/assistant"): (20, 60),
            ("POST", "/agent/chat"): (20, 60),
        }
        self.max_content_length = int(os.getenv("MAX_REQUEST_BYTES", str(16 * 1024 * 1024)))

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = str(uuid.uuid4())
        path = request.url.path
        method = request.method.upper()

        # Content-Length is only an early rejection. Streaming routes must still
        # enforce their own actual byte limits (the voice route already does so).
        if path in {"/voice/assistant", "/agent/chat"}:
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    if int(content_length) > self.max_content_length:
                        response = JSONResponse(
                            status_code=413,
                            content={"detail": "Request body is too large."},
                        )
                        return self._headers(response, request_id)
                except ValueError:
                    response = JSONResponse(
                        status_code=400,
                        content={"detail": "Invalid Content-Length header."},
                    )
                    return self._headers(response, request_id)

        rule = self.rules.get((method, path))
        if rule:
            limit, window = rule
            # Do not trust X-Forwarded-For here: clients can spoof it unless a
            # trusted reverse proxy strips/replaces it. Configure limits at the
            # proxy/API gateway for accurate client IPs in production.
            client_ip = request.client.host if request.client else "unknown"
            allowed, retry_after = self.limiter.allow((f"{client_ip}:{path}", method), limit, window)
            if not allowed:
                response = JSONResponse(
                    status_code=429,
                    content={"detail": "Too many requests. Please try again later."},
                    headers={"Retry-After": str(retry_after)},
                )
                return self._headers(response, request_id)

        try:
            response = await call_next(request)
        except Exception:
            # Let the app's exception handlers manage the response; avoid logging
            # request bodies, credentials, or provider payloads in this middleware.
            raise
        return self._headers(response, request_id)

    def _headers(self, response: Response, request_id: str) -> Response:
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Permissions-Policy"] = "camera=(self), microphone=(self), geolocation=()"
        response.headers["Cache-Control"] = "no-store"
        if self.app_env == "production":
            response.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return response


def install_security_controls(app: FastAPI) -> None:
    """Install host validation, optional CORS, request limits, and rate limits.

    Environment variables:
      APP_ENV=development|production
      ALLOWED_HOSTS=voice-support-agent.onrender.com,localhost
      CORS_ALLOWED_ORIGINS=https://admin.example.com, https://voice-support-agent.onrender.com
      MAX_REQUEST_BYTES=16777216
    """
    app_env = os.getenv("APP_ENV", "development").strip().lower()
    if app_env not in {"development", "test", "production"}:
        raise RuntimeError("APP_ENV must be development, test, or production.")

    hosts_raw = os.getenv("ALLOWED_HOSTS", "")
    if hosts_raw.strip():
        allowed_hosts = [host.strip() for host in hosts_raw.split(",") if host.strip()]
    elif app_env == "production":
        raise RuntimeError("ALLOWED_HOSTS must be configured when APP_ENV=production.")
    else:
        allowed_hosts = ["localhost", "127.0.0.1", "testserver"]

    app.add_middleware(TrustedHostMiddleware, allowed_hosts=allowed_hosts)

    origins_raw = os.getenv("CORS_ALLOWED_ORIGINS", "")
    origins = [origin.strip() for origin in origins_raw.split(",") if origin.strip()]
    if origins:
        # Bearer-token authentication does not require credentialed CORS.
        # Keep origins explicit; wildcard origins are intentionally rejected.
        if "*" in origins:
            raise RuntimeError("CORS_ALLOWED_ORIGINS must list explicit origins, not '*'.")
        app.add_middleware(
            CORSMiddleware,
            allow_origins=origins,
            allow_credentials=False,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
            max_age=600,
        )

    app.add_middleware(SecurityControlsMiddleware, app_env=app_env)
