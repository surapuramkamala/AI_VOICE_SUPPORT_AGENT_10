# Step 2 — Security configuration patch

## File added

- `app/security.py` — adds route-specific rate limits, request-size early rejection, request IDs, response security headers, optional explicit-origin CORS, and trusted-host validation.

## Wire it into the application

In the authenticated project's root `main.py`, add this import:

```python
from app.security import install_security_controls
```

After the FastAPI application is created (immediately after `app = FastAPI(...)` is a suitable place), add:

```python
install_security_controls(app)
```

Keep existing authentication, customer-scoping dependencies, and refund safeguards unchanged. If the application already adds the same security headers, the middleware may set those headers again to the same values; remove duplicate header logic only after verifying the behavior.

## Environment configuration

For local development:

```env
APP_ENV=development
ALLOWED_HOSTS=localhost,127.0.0.1,testserver
CORS_ALLOWED_ORIGINS=
MAX_REQUEST_BYTES=16777216
```

For deployment, set explicit values, for example:

```env
APP_ENV=production
ALLOWED_HOSTS=api.example.com
CORS_ALLOWED_ORIGINS=https://app.example.com
MAX_REQUEST_BYTES=16777216
```

Replace the example hostnames with your actual deployment domains. If the browser UI is served by the same FastAPI origin, leave `CORS_ALLOWED_ORIGINS` empty; same-origin requests do not need CORS.

## Default rate limits

- `POST /auth/login`: 5 requests per minute per client IP.
- `POST /voice/assistant`: 20 requests per minute per client IP.
- `POST /agent/chat`: 20 requests per minute per client IP.

These are conservative starting values, not universal production limits. Voice traffic may need tuning after measuring real use.

## Important limitations

- The limiter is process-local. It resets on restart and is not shared between workers/instances. Use a reverse proxy/API gateway or a shared Redis-backed limiter for production multi-worker deployments.
- The middleware intentionally does not trust `X-Forwarded-For`, which can be spoofed if the proxy is not configured correctly. Configure the trusted proxy to strip incoming forwarding headers and set them itself, then use gateway-level rate limiting.
- `Content-Length` is an early rejection only; it can be absent or untrusted. The voice endpoint must keep enforcing its actual upload byte limit while reading the stream.
- `TrustedHostMiddleware` requires `ALLOWED_HOSTS` to include the public hostname in production. Do not use `*` for production hosts or CORS origins.
- HSTS is added only when `APP_ENV=production`; only enable production mode when HTTPS is configured at the edge.
- No application code can replace TLS, secret management, monitoring, or gateway-level request limits.

## Verification checklist

1. Start locally with `APP_ENV=development` and `ALLOWED_HOSTS=localhost,127.0.0.1,testserver`.
2. Confirm `/voice-ui` and normal API requests still work.
3. Send six login attempts from the same client within one minute; the sixth should return HTTP 429 with `Retry-After`.
4. Confirm responses include `X-Request-ID`, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, and `Permissions-Policy`.
5. Confirm an unlisted `Host` header is rejected with HTTP 400.
6. Set `APP_ENV=production` without `ALLOWED_HOSTS`; startup should fail fast.
7. Confirm authenticated customer access and refund confirmation/approval tests still pass.
