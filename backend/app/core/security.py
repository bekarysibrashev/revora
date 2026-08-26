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


def normalize_phone_e164(value: str) -> str:
    """Return one stable E.164-like representation for cross-source matching.

    1C, Kcell and WhatsApp format Kazakhstan numbers differently.  The shared
    representation mirrors the local 1C connector: 10 local digits get country
    code 7 and an 11 digit number beginning with 8 is converted to 7.
    """

    digits = "".join(character for character in str(value) if character.isdigit())
    if len(digits) == 11 and digits.startswith("8"):
        digits = "7" + digits[1:]
    elif len(digits) == 10:
        digits = "7" + digits
    if not 10 <= len(digits) <= 15:
        raise ValueError("phone must contain between 10 and 15 digits")
    return f"+{digits}"


def phone_hash(value: str) -> str:
    return hashlib.sha256(normalize_phone_e164(value).encode("utf-8")).hexdigest()


def phone_hash_candidates(value: str) -> set[str]:
    """Hashes used by current and legacy integrations for a single phone.

    Legacy Kcell/WhatsApp rows hashed the provider string verbatim.  Keeping
    those candidates lets a newly received contact match history created before
    canonical phone normalization was introduced.
    """

    raw = str(value).strip()
    digits = "".join(character for character in raw if character.isdigit())
    normalized = normalize_phone_e164(raw)
    variants = {raw, digits, normalized}
    normalized_digits = normalized[1:]
    variants.add(normalized_digits)
    if normalized_digits.startswith("7") and len(normalized_digits) == 11:
        variants.add("8" + normalized_digits[1:])
    return {
        hashlib.sha256(item.encode("utf-8")).hexdigest()
        for item in variants
        if item
    }


def mask_phone(value: str) -> str:
    digits = "".join(character for character in str(value) if character.isdigit())
    return f"***{digits[-4:]}" if len(digits) >= 4 else "***"
