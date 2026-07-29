import base64
import hashlib
import hmac

from cryptography.fernet import Fernet, InvalidToken


class WhatsAppDataProtectionError(RuntimeError):
    pass


def _fernet(secret: str) -> Fernet:
    if len(secret) < 24:
        raise WhatsAppDataProtectionError("WHATSAPP_DATA_KEY is not configured")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_contact(value: str, secret: str) -> str:
    return _fernet(secret).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_contact(value: str, secret: str) -> str:
    try:
        return _fernet(secret).decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise WhatsAppDataProtectionError("WhatsApp contact data cannot be decrypted") from exc


def contact_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def mask_contact(value: str) -> str:
    digits = "".join(character for character in value if character.isdigit())
    return f"***{digits[-4:]}" if len(digits) >= 4 else "***"


def valid_meta_signature(body: bytes, signature: str, app_secret: str) -> bool:
    if not app_secret or not signature.startswith("sha256="):
        return False
    expected = hmac.new(app_secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature[7:], expected)
