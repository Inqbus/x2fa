import base64
import hashlib
import secrets

import bcrypt
from cryptography.fernet import Fernet


class CryptoService:
    """Cryptography service: Fernet encryption + bcrypt hashing."""

    def __init__(self, secret: str):
        # Derive Fernet key from secret (deterministic, 32 bytes)
        key_bytes = hashlib.sha256(secret.encode()).digest()
        self._fernet = Fernet(base64.urlsafe_b64encode(key_bytes))

    def get_fernet(self) -> Fernet:
        return self._fernet

    def encrypt(self, plaintext: str) -> bytes:
        return self._fernet.encrypt(plaintext.encode())

    def decrypt(self, ciphertext: bytes) -> str:
        return self._fernet.decrypt(ciphertext).decode()

    @staticmethod
    def hash_backup_code(code: str) -> str:
        return bcrypt.hashpw(code.encode(), bcrypt.gensalt(rounds=12)).decode()

    @staticmethod
    def verify_backup_code(code: str, code_hash: str) -> bool:
        return bcrypt.checkpw(code.encode(), code_hash.encode())

    @staticmethod
    def generate_backup_codes(count: int = 10) -> list[str]:
        """Generates single-use 8-character hex codes (uppercase)."""
        return [secrets.token_hex(4).upper() for _ in range(count)]
