"""Password, JWT and one-way token primitives."""

from datetime import UTC, datetime, timedelta
import hashlib
import secrets
from typing import Any
from uuid import UUID, uuid4

from jose import JWTError, jwt
from passlib.context import CryptContext

from app.core.config import Settings

password_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class InvalidAccessToken(ValueError):
    pass


def hash_password(password: str) -> str:
    return password_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return password_context.verify(password, password_hash)


def create_access_token(
    *, user_id: UUID, tenant_id: UUID, role: str, branch_ids: list[UUID], settings: Settings
) -> tuple[str, datetime]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=settings.access_token_expire_minutes)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "branch_ids": [str(branch_id) for branch_id in branch_ids],
        "type": "access",
        "jti": str(uuid4()),
        "iat": now,
        "exp": expires_at,
    }
    token = jwt.encode(
        payload,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )
    return token, expires_at


def decode_access_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        if payload.get("type") != "access" or not payload.get("sub") or not payload.get("tenant_id"):
            raise InvalidAccessToken("Invalid access token claims")
        UUID(payload["sub"])
        UUID(payload["tenant_id"])
        return payload
    except (JWTError, KeyError, TypeError, ValueError) as exc:
        raise InvalidAccessToken("Invalid or expired access token") from exc


def generate_refresh_token() -> str:
    return secrets.token_urlsafe(64)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def phone_hash(phone_e164: str) -> str:
    return hashlib.sha256(phone_e164.encode("utf-8")).hexdigest()
