import os
import secrets
import sys
from datetime import datetime, timedelta, timezone

import bcrypt
import jwt
from cryptography.fernet import Fernet

# ---------------------------------------------------------------------------
# Konfiguration
# ---------------------------------------------------------------------------

_JWT_ALGORITHM = "HS256"
_JWT_SECRET: str | None = None
_FERNET: Fernet | None = None


def init_crypto(secret: str) -> None:
    """Muss einmalig beim Start mit dem validierten X2FA_SECRET aufgerufen werden."""
    global _JWT_SECRET, _FERNET

    _JWT_SECRET = secret

    # Fernet benötigt exakt 32 Bytes (URL-safe Base64). Wir leiten den Key
    # deterministisch aus X2FA_SECRET ab, damit er nach Neustart identisch ist.
    import base64
    import hashlib
    key_bytes = hashlib.sha256(secret.encode()).digest()
    _FERNET = Fernet(base64.urlsafe_b64encode(key_bytes))


def _require_init() -> None:
    if _JWT_SECRET is None or _FERNET is None:
        raise RuntimeError("crypto.init_crypto() wurde nicht aufgerufen.")


# ---------------------------------------------------------------------------
# Fernet (TOTP-Secrets)
# ---------------------------------------------------------------------------

def encrypt_totp_secret(plaintext: str) -> bytes:
    _require_init()
    return _FERNET.encrypt(plaintext.encode())


def decrypt_totp_secret(ciphertext: bytes) -> str:
    _require_init()
    return _FERNET.decrypt(ciphertext).decode()


# ---------------------------------------------------------------------------
# bcrypt (Backup-Codes)
# ---------------------------------------------------------------------------

def hash_backup_code(code: str) -> str:
    return bcrypt.hashpw(code.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_backup_code(code: str, code_hash: str) -> bool:
    return bcrypt.checkpw(code.encode(), code_hash.encode())


# ---------------------------------------------------------------------------
# Backup-Code Generierung
# ---------------------------------------------------------------------------

def generate_backup_codes(count: int = 10) -> list[str]:
    """Erzeugt `count` einmalige 8-stellige Hex-Codes (Großbuchstaben)."""
    return [secrets.token_hex(4).upper() for _ in range(count)]


# ---------------------------------------------------------------------------
# JWT
# ---------------------------------------------------------------------------

def create_jwt(payload: dict, expiry_minutes: int, add_jti: bool = False) -> str:
    _require_init()
    data = payload.copy()
    data["exp"] = datetime.now(tz=timezone.utc) + timedelta(minutes=expiry_minutes)
    if add_jti and "jti" not in data:
        data["jti"] = secrets.token_urlsafe(16)
    return jwt.encode(data, _JWT_SECRET, algorithm=_JWT_ALGORITHM)


def verify_jwt(token: str) -> dict:
    """Gibt den decodierten Payload zurück oder wirft jwt.exceptions.*."""
    _require_init()
    return jwt.decode(token, _JWT_SECRET, algorithms=[_JWT_ALGORITHM])
