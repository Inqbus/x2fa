"""CA and client certificate operations using the cryptography library directly."""

import os
from datetime import datetime, timezone, timedelta
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def generate_ca(
    cn: str,
    validity_days: int,
    key_path: str,
    cert_path: str,
) -> None:
    """Generate a self-signed EC P-256 CA certificate.

    Writes the private key (mode 0600) and the certificate as PEM files.
    Raises on any failure — caller wraps in try/except.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=validity_days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                key_cert_sign=True,
                crl_sign=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(key, hashes.SHA256())
    )

    key_p = Path(key_path)
    key_p.parent.mkdir(parents=True, exist_ok=True)
    key_p.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    os.chmod(key_p, 0o600)
    os.chmod(key_p.parent, 0o755)

    cert_p = Path(cert_path)
    cert_p.parent.mkdir(parents=True, exist_ok=True)
    cert_p.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    os.chmod(cert_p.parent, 0o755)


def issue_client_cert(
    client_id: str,
    ca_cert_path: str,
    ca_key_path: str,
    output_dir: str,
    validity_days: int = 90,
) -> dict[str, str]:
    """Issue a client certificate signed by the named CA.

    Returns {'key': path, 'cert': path, 'ca': path}.
    Raises on any failure.
    """
    ca_cert = x509.load_pem_x509_certificate(Path(ca_cert_path).read_bytes())
    ca_key = serialization.load_pem_private_key(
        Path(ca_key_path).read_bytes(), password=None
    )

    client_key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, client_id)])
    now = datetime.now(timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(client_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + timedelta(days=validity_days))
        .sign(ca_key, hashes.SHA256())
    )

    safe_id = client_id.replace("/", "_").replace(":", "_")
    out = Path(output_dir)
    out.mkdir(parents=True, exist_ok=True, mode=0o755)

    paths = {
        "key": str(out / f"{safe_id}.key.pem"),
        "cert": str(out / f"{safe_id}.cert.pem"),
        "ca": str(out / f"{safe_id}.ca.pem"),
    }

    key_file = Path(paths["key"])
    key_file.write_bytes(
        client_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    os.chmod(key_file, 0o600)
    Path(paths["cert"]).write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    Path(paths["ca"]).write_bytes(Path(ca_cert_path).read_bytes())

    return paths


def get_cert_info(cert_pem_path: str) -> dict:
    """Return display info for a PEM certificate file."""
    try:
        cert = x509.load_pem_x509_certificate(Path(cert_pem_path).read_bytes())
        cn_attrs = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)
        return {
            "cn": cn_attrs[0].value if cn_attrs else "(no CN)",
            "expires": cert.not_valid_after_utc.date().isoformat(),
            "fingerprint": cert.fingerprint(hashes.SHA256()).hex(":"),
        }
    except Exception as exc:
        return {"error": str(exc)}
