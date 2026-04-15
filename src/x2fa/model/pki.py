from datetime import datetime, timezone

from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric.padding import PKCS1v15
from cryptography.hazmat.primitives.asymmetric.ec import ECDSA
from cryptography.exceptions import InvalidSignature
from cryptography.x509.oid import NameOID

from sqlalchemy.sql.schema import Column
from sqlalchemy.sql.sqltypes import String, Integer, Boolean, DateTime, Text

from x2fa.model.base import Base


class TrustedCA(Base):
    """A trusted Certificate Authority used to authenticate OIDC clients via mTLS."""

    __tablename__ = "trusted_ca"

    id         = Column(Integer, primary_key=True, autoincrement=True)
    name       = Column(String(100), nullable=False, unique=True)
    cert_pem   = Column(Text, nullable=False)   # PEM-encoded root or intermediate CA cert
    active     = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime, nullable=True)  # None = not tracked

    def verify_certificate(self, client_cert_pem: str) -> dict:
        """Validates client_cert_pem against this CA.

        Returns {'valid': True, 'client_id': <CN>} on success,
        or {'valid': False, 'reason': <str>} on failure.

        Checks:
        - PEM is a valid X.509 certificate
        - Certificate is within its validity period
        - Certificate is signed by this CA
        - CN attribute is present (used as client_id)
        """
        try:
            client_cert = x509.load_pem_x509_certificate(client_cert_pem.encode())
        except Exception as exc:
            return {"valid": False, "reason": f"Failed to parse client certificate: {exc}"}

        now = datetime.now(timezone.utc)
        not_before = client_cert.not_valid_before_utc
        not_after  = client_cert.not_valid_after_utc

        if now < not_before:
            return {"valid": False, "reason": "Certificate not yet valid"}
        if now > not_after:
            return {"valid": False, "reason": "Certificate has expired"}

        try:
            ca_cert = x509.load_pem_x509_certificate(self.cert_pem.encode())
        except Exception as exc:
            return {"valid": False, "reason": f"Failed to parse CA certificate: {exc}"}

        ca_public_key = ca_cert.public_key()
        try:
            key_type = type(ca_public_key).__name__
            if "RSA" in key_type:
                ca_public_key.verify(
                    client_cert.signature,
                    client_cert.tbs_certificate_bytes,
                    PKCS1v15(),
                    client_cert.signature_hash_algorithm,
                )
            elif "EC" in key_type:
                ca_public_key.verify(
                    client_cert.signature,
                    client_cert.tbs_certificate_bytes,
                    ECDSA(client_cert.signature_hash_algorithm),
                )
            else:
                return {"valid": False, "reason": f"Unsupported CA key type: {key_type}"}
        except InvalidSignature:
            return {"valid": False, "reason": "Certificate signature is invalid"}
        except Exception as exc:
            return {"valid": False, "reason": f"Signature verification failed: {exc}"}

        try:
            cn = client_cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        except (IndexError, Exception):
            return {"valid": False, "reason": "Certificate has no CN attribute"}

        return {"valid": True, "client_id": cn}
