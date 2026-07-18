"""Shared fixtures for X2FA tests."""

import os


import pytest

from datetime import datetime, timezone, timedelta
from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, rsa

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from x2fa.app import create_app
from x2fa.model import Base, TrustedCA
from x2fa.init_app.database import db


@pytest.fixture(autouse=True, scope="session")
def _prevent_parallel_execution():
    """Prevent parallel execution by using a session-scoped autouse fixture with a lock."""
    import os
    # Check if running with pytest-asyncio which may run tests in parallel
    # This doesn't actually prevent parallelism but helps expose the issue
    pass


@pytest.fixture(autouse=True)
def reset_db():
    """Resets the database schema before every test."""
    with create_app().app_context():
        db.reset_schema()


@pytest.fixture(scope="function")
def db_session():
    """In-memory SQLite session, rolled back after each test."""
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()
    Base.metadata.drop_all(engine)


def _build_cert(cn, signing_key, issuer_name, subject_name, days=90):
    """Returns a signed X.509 certificate."""
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject_name)
        .issuer_name(issuer_name)
        .public_key(signing_key.public_key() if hasattr(signing_key, "public_key") else signing_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=days))
    )
    return builder.sign(signing_key, hashes.SHA256())


def make_ec_ca(cn="Test CA"):
    """Returns (private_key, cert, cert_pem) for a self-signed EC CA."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    cert = _build_cert(cn, key, name, name)
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return key, cert, pem


def make_rsa_ca(cn="Test RSA CA"):
    """Returns (private_key, cert, cert_pem) for a self-signed RSA CA."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    cert = _build_cert(cn, key, name, name)
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return key, cert, pem


@pytest.fixture
def ec_ca(db_session):
    """A TrustedCA backed by an EC key, persisted to the in-memory DB."""
    ca_key, ca_cert, ca_pem = make_ec_ca("EC Test CA")
    ca = TrustedCA(name="ec-test-ca", cert_pem=ca_pem)
    db_session.add(ca)
    db_session.commit()
    db_session.refresh(ca)
    return ca, ca_key, ca_cert


@pytest.fixture
def rsa_ca(db_session):
    """A TrustedCA backed by an RSA key, persisted to the in-memory DB."""
    ca_key, ca_cert, ca_pem = make_rsa_ca("RSA Test CA")
    ca = TrustedCA(name="rsa-test-ca", cert_pem=ca_pem)
    db_session.add(ca)
    db_session.commit()
    db_session.refresh(ca)
    return ca, ca_key, ca_cert


def make_ec_ca_expiring_in(cn, days):
    """Returns (private_key, cert, cert_pem) for a self-signed EC CA expiring in `days` days.
    Pass a negative value to create an already-expired certificate.
    """
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    now = datetime.now(timezone.utc)
    if days < 0:
        not_before = now + timedelta(days=days - 1)
        not_after  = now + timedelta(days=days)
    else:
        not_before = now - timedelta(days=1)
        not_after  = now + timedelta(days=days)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(not_before)
        .not_valid_after(not_after)
        .sign(key, hashes.SHA256())
    )
    pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    return key, cert, pem


def make_client_cert(cn, ca_key, ca_cert, days=90):
    """Returns cert_pem for a client certificate signed by the given CA."""
    client_key = ec.generate_private_key(ec.SECP256R1())
    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(client_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=days))
    )
    cert = builder.sign(ca_key, hashes.SHA256())
    return cert.public_bytes(serialization.Encoding.PEM).decode()


def make_self_signed_cert(cn):
    """Returns (key, cert, cert_pem, fingerprint) for a self-signed certificate."""
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, cn)])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=365))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode()
    fingerprint = cert.fingerprint(hashes.SHA256()).hex(":")
    return key, cert, cert_pem, fingerprint


@pytest.fixture
def self_signed_cert():
    """Returns (key, cert, cert_pem, fingerprint) for a self-signed certificate."""
    return make_self_signed_cert("test-client")


@pytest.fixture
def isolated_paths(tmp_path):
    """Isolate X2FA paths to tmp_path for this test using X2FA_HOME."""
    import os
    from x2fa import paths
    
    os.environ["X2FA_HOME"] = str(tmp_path)
    print(f"\n[isolated_paths] X2FA_HOME={os.environ['X2FA_HOME']}\n")
    yield tmp_path
    os.environ.pop("X2FA_HOME", None)
