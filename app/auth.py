"""Authentication helpers: signed short-lived bearer tokens and role checks."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import secrets
import time
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import UserAccount

TOKEN_TTL_SECONDS = int(os.getenv("ACCESS_TOKEN_TTL_SECONDS", "1800"))
ALGORITHM = "HS256"
bearer_scheme = HTTPBearer(auto_error=False)


def _secret() -> bytes:
    secret = os.getenv("JWT_SECRET_KEY", "")
    if len(secret) < 32 or secret in {"change-me", "replace-me"}:
        raise RuntimeError(
            "JWT_SECRET_KEY must be configured with at least 32 characters. "
            "Generate one with: python -c \"import secrets; print(secrets.token_urlsafe(48))\""
        )
    return secret.encode("utf-8")


def hash_password(password: str, *, salt: bytes | None = None) -> str:
    if len(password) < 12 or len(password) > 256:
        raise ValueError("Password must be between 12 and 256 characters.")
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
    return f"pbkdf2_sha256$310000${base64.urlsafe_b64encode(salt).decode()}${base64.urlsafe_b64encode(digest).decode()}"


def verify_password(password: str, encoded: str) -> bool:
    try:
        scheme, rounds, salt_text, digest_text = encoded.split("$", 3)
        if scheme != "pbkdf2_sha256" or int(rounds) != 310_000:
            return False
        salt = base64.urlsafe_b64decode(salt_text.encode())
        expected = base64.urlsafe_b64decode(digest_text.encode())
        actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 310_000)
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def create_access_token(account: UserAccount) -> str:
    now = int(time.time())
    header = {"alg": ALGORITHM, "typ": "JWT"}
    payload: dict[str, Any] = {
        "sub": str(account.id),
        "email": account.email,
        "role": account.role,
        "customer_id": account.customer_id,
        "iat": now,
        "exp": now + TOKEN_TTL_SECONDS,
        "iss": "ai-voice-support-agent",
        "aud": "ai-voice-support-api",
    }
    signing_input = f"{_b64(json.dumps(header, separators=(',', ':')).encode())}.{_b64(json.dumps(payload, separators=(',', ':')).encode())}"
    signature = hmac.new(_secret(), signing_input.encode(), hashlib.sha256).digest()
    return f"{signing_input}.{_b64(signature)}"


def decode_access_token(token: str) -> dict[str, Any]:
    try:
        header_part, payload_part, signature_part = token.split(".")
        header = json.loads(base64.urlsafe_b64decode(header_part + "=" * (-len(header_part) % 4)))
        if header != {"alg": ALGORITHM, "typ": "JWT"}:
            raise ValueError("Unexpected token algorithm or header")
        signing_input = f"{header_part}.{payload_part}"
        expected = hmac.new(_secret(), signing_input.encode(), hashlib.sha256).digest()
        actual = base64.urlsafe_b64decode(signature_part + "=" * (-len(signature_part) % 4))
        if not hmac.compare_digest(actual, expected):
            raise ValueError("Invalid signature")
        claims = json.loads(base64.urlsafe_b64decode(payload_part + "=" * (-len(payload_part) % 4)))
        now = int(time.time())
        if claims.get("iss") != "ai-voice-support-agent" or claims.get("aud") != "ai-voice-support-api":
            raise ValueError("Invalid token issuer or audience")
        if not isinstance(claims.get("exp"), int) or claims["exp"] <= now:
            raise ValueError("Expired token")
        if not isinstance(claims.get("sub"), str) or not claims.get("role"):
            raise ValueError("Missing required claims")
        return claims
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token.",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc


def get_current_account(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> UserAccount:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise HTTPException(status_code=401, detail="Bearer access token required.", headers={"WWW-Authenticate": "Bearer"})
    claims = decode_access_token(credentials.credentials)
    try:
        account_id = int(claims["sub"])
    except (ValueError, TypeError) as exc:
        raise HTTPException(status_code=401, detail="Invalid access token.") from exc
    account = db.scalar(select(UserAccount).where(UserAccount.id == account_id, UserAccount.is_active.is_(True)))
    if account is None or account.role != claims.get("role") or account.customer_id != claims.get("customer_id"):
        raise HTTPException(status_code=401, detail="Invalid or revoked access token.")
    return account


def get_current_customer_id(account: UserAccount = Depends(get_current_account)) -> int:
    if account.role != "customer" or account.customer_id is None:
        raise HTTPException(status_code=403, detail="A customer account is required.")
    return account.customer_id


def require_reviewer(account: UserAccount = Depends(get_current_account)) -> UserAccount:
    if account.role != "reviewer":
        raise HTTPException(status_code=403, detail="A reviewer account is required.")
    return account
