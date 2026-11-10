"""Encryption helpers for reversible patient data shown to authorised staff."""

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken


class SensitiveDataProtectionError(RuntimeError):
    """The configured data-protection key cannot safely encrypt/decrypt data."""


def _fernet(secret: str, *, setting_name: str) -> Fernet:
    if len(secret) < 24:
        raise SensitiveDataProtectionError(f"{setting_name} is not configured")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_sensitive_text(value: str, secret: str, *, setting_name: str) -> str:
    return _fernet(secret, setting_name=setting_name).encrypt(value.encode("utf-8")).decode("ascii")


def decrypt_sensitive_text(value: str, secret: str, *, setting_name: str) -> str:
    try:
        return _fernet(secret, setting_name=setting_name).decrypt(value.encode("ascii")).decode("utf-8")
    except InvalidToken as exc:
        raise SensitiveDataProtectionError(f"{setting_name} cannot decrypt stored data") from exc
