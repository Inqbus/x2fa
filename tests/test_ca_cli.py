"""Tests for CA management CLI commands (add-ca, list-cas, revoke-ca, issue-client-cert)."""

import pytest
from flask.cli import FlaskGroup
from click.testing import CliRunner
from cryptography.hazmat.primitives import serialization

from x2fa.app import create_app
from x2fa.models import TrustedCA
from x2fa.init_app.database import db
from tests.conftest import make_ec_ca, make_ec_ca_expiring_in, make_client_cert


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cli():
    return FlaskGroup(create_app=create_app)


def _write_ca_files(tmp_path, name="test-ca"):
    """Writes CA key + cert PEM files to tmp_path, returns (key_path, cert_path)."""
    ca_key, ca_cert, ca_pem = make_ec_ca(name)
    cert_path = tmp_path / "ca.cert.pem"
    key_path  = tmp_path / "ca.key.pem"
    cert_path.write_text(ca_pem)
    key_path.write_bytes(
        ca_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return key_path, cert_path, ca_key, ca_cert, ca_pem


# ---------------------------------------------------------------------------
# add-ca
# ---------------------------------------------------------------------------

def test_add_ca_success(tmp_path):
    """Registers a valid CA certificate."""
    _, cert_path, _, _, _ = _write_ca_files(tmp_path)
    runner = CliRunner()

    result = runner.invoke(_cli(), ["add-ca", "my-ca", str(cert_path)])

    assert result.exit_code == 0, result.output
    assert "CA registered:  my-ca" in result.output
    assert "Expires:" in result.output
    assert "Fingerprint:" in result.output


def test_add_ca_invalid_pem(tmp_path):
    """Rejects a file that is not a valid PEM certificate."""
    bad_file = tmp_path / "bad.pem"
    bad_file.write_text("this is not a certificate")
    runner = CliRunner()

    result = runner.invoke(_cli(), ["add-ca", "bad-ca", str(bad_file)])

    assert result.exit_code != 0
    assert "Not a valid PEM certificate" in result.output


def test_add_ca_duplicate_rejected(tmp_path):
    """Refuses to register a CA name that already exists."""
    _, cert_path, _, _, _ = _write_ca_files(tmp_path)
    runner = CliRunner()

    runner.invoke(_cli(), ["add-ca", "dupe-ca", str(cert_path)])
    result = runner.invoke(_cli(), ["add-ca", "dupe-ca", str(cert_path)])

    assert result.exit_code != 0
    assert "already exists" in result.output


# ---------------------------------------------------------------------------
# list-cas
# ---------------------------------------------------------------------------

def test_list_cas_empty():
    """Reports 'No CAs registered' on a fresh database."""
    runner = CliRunner()

    result = runner.invoke(_cli(), ["list-cas"])

    assert result.exit_code == 0, result.output
    assert "No CAs registered." in result.output


def test_list_cas_shows_registered(tmp_path):
    """Lists all registered CAs with name and status."""
    _, cert_path, _, _, _ = _write_ca_files(tmp_path, "list-test-ca")
    runner = CliRunner()
    runner.invoke(_cli(), ["add-ca", "list-test-ca", str(cert_path)])

    result = runner.invoke(_cli(), ["list-cas"])

    assert result.exit_code == 0, result.output
    assert "list-test-ca" in result.output
    assert "active" in result.output


# ---------------------------------------------------------------------------
# revoke-ca
# ---------------------------------------------------------------------------

def test_revoke_ca_success(tmp_path):
    """Deactivates a registered CA."""
    _, cert_path, _, _, _ = _write_ca_files(tmp_path, "revoke-me")
    runner = CliRunner()
    runner.invoke(_cli(), ["add-ca", "revoke-me", str(cert_path)])

    result = runner.invoke(_cli(), ["revoke-ca", "revoke-me"])

    assert result.exit_code == 0, result.output
    assert "revoked" in result.output

    with create_app().app_context():
        with db.session_scope() as session:
            from sqlalchemy import select
            ca = session.execute(
                select(TrustedCA).where(TrustedCA.name == "revoke-me")
            ).scalars().first()
            assert ca.active is False


def test_revoke_ca_not_found():
    """Fails gracefully when the CA name does not exist."""
    runner = CliRunner()

    result = runner.invoke(_cli(), ["revoke-ca", "nonexistent-ca"])

    assert result.exit_code != 0
    assert "not found" in result.output.lower()


def test_revoke_ca_already_revoked(tmp_path):
    """Reports that a CA is already revoked without error."""
    _, cert_path, _, _, _ = _write_ca_files(tmp_path, "already-gone")
    runner = CliRunner()
    runner.invoke(_cli(), ["add-ca", "already-gone", str(cert_path)])
    runner.invoke(_cli(), ["revoke-ca", "already-gone"])

    result = runner.invoke(_cli(), ["revoke-ca", "already-gone"])

    assert result.exit_code == 0, result.output
    assert "already revoked" in result.output


# ---------------------------------------------------------------------------
# init-db
# ---------------------------------------------------------------------------

def test_init_db_creates_tables():
    """init-db creates all tables so subsequent commands work on a fresh DB."""
    runner = CliRunner()

    # Drop all tables first to simulate a fresh database
    with create_app().app_context():
        from x2fa.models import Base
        Base.metadata.drop_all(db.engine)

    result = runner.invoke(_cli(), ["init-db"])

    assert result.exit_code == 0, result.output
    assert "Database tables created." in result.output

    # list-cas must work without OperationalError now
    result = runner.invoke(_cli(), ["list-cas"])
    assert result.exit_code == 0, result.output


# ---------------------------------------------------------------------------
# list-cas expiry warnings
# ---------------------------------------------------------------------------

def test_list_cas_warns_expired(tmp_path):
    """Marks an expired CA with *** EXPIRED ***."""
    _, _, ca_pem = make_ec_ca_expiring_in("expired-ca", days=-1)
    cert_path = tmp_path / "expired.cert.pem"
    cert_path.write_text(ca_pem)
    runner = CliRunner()
    runner.invoke(_cli(), ["add-ca", "expired-ca", str(cert_path)])

    result = runner.invoke(_cli(), ["list-cas"])

    assert result.exit_code == 0, result.output
    assert "EXPIRED" in result.output


def test_list_cas_warns_expiring_soon(tmp_path):
    """Marks a CA expiring within 30 days with 'expires soon'."""
    _, _, ca_pem = make_ec_ca_expiring_in("soon-ca", days=15)
    cert_path = tmp_path / "soon.cert.pem"
    cert_path.write_text(ca_pem)
    runner = CliRunner()
    runner.invoke(_cli(), ["add-ca", "soon-ca", str(cert_path)])

    result = runner.invoke(_cli(), ["list-cas"])

    assert result.exit_code == 0, result.output
    assert "expires soon" in result.output


# ---------------------------------------------------------------------------
# issue-client-cert
# ---------------------------------------------------------------------------

def test_issue_client_cert_success(tmp_path):
    """Issues a client certificate and writes three PEM files."""
    key_path, cert_path, _, _, _ = _write_ca_files(tmp_path, "issuing-ca")
    runner = CliRunner()
    runner.invoke(_cli(), ["add-ca", "issuing-ca", str(cert_path)])

    result = runner.invoke(
        _cli(),
        ["issue-client-cert", "shop.example.com", "--ca", "issuing-ca", "--output", str(tmp_path)],
        input=str(key_path) + "\n",
    )

    assert result.exit_code == 0, result.output
    assert (tmp_path / "shop.example.com.key.pem").exists()
    assert (tmp_path / "shop.example.com.cert.pem").exists()
    assert (tmp_path / "shop.example.com.ca.pem").exists()


def test_issue_client_cert_cn_is_client_id(tmp_path):
    """The issued certificate has CN equal to the client_id argument."""
    from cryptography import x509
    from cryptography.x509.oid import NameOID

    key_path, cert_path, _, _, _ = _write_ca_files(tmp_path, "cn-check-ca")
    runner = CliRunner()
    runner.invoke(_cli(), ["add-ca", "cn-check-ca", str(cert_path)])
    runner.invoke(
        _cli(),
        ["issue-client-cert", "api.example.com", "--ca", "cn-check-ca", "--output", str(tmp_path)],
        input=str(key_path) + "\n",
    )

    cert_pem = (tmp_path / "api.example.com.cert.pem").read_bytes()
    cert = x509.load_pem_x509_certificate(cert_pem)
    cn = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
    assert cn == "api.example.com"


def test_issue_client_cert_key_is_mode_600(tmp_path):
    """The private key file is written with mode 0600."""
    import stat

    key_path, cert_path, _, _, _ = _write_ca_files(tmp_path, "mode-ca")
    runner = CliRunner()
    runner.invoke(_cli(), ["add-ca", "mode-ca", str(cert_path)])
    runner.invoke(
        _cli(),
        ["issue-client-cert", "secure.example.com", "--ca", "mode-ca", "--output", str(tmp_path)],
        input=str(key_path) + "\n",
    )

    key_file = tmp_path / "secure.example.com.key.pem"
    mode = stat.S_IMODE(key_file.stat().st_mode)
    assert mode == 0o600


def test_issue_client_cert_inactive_ca_rejected(tmp_path):
    """Refuses to issue a certificate when the CA has been revoked."""
    key_path, cert_path, _, _, _ = _write_ca_files(tmp_path, "inactive-ca")
    runner = CliRunner()
    runner.invoke(_cli(), ["add-ca", "inactive-ca", str(cert_path)])
    runner.invoke(_cli(), ["revoke-ca", "inactive-ca"])

    result = runner.invoke(
        _cli(),
        ["issue-client-cert", "client.example.com", "--ca", "inactive-ca", "--output", str(tmp_path)],
        input=str(key_path) + "\n",
    )

    assert result.exit_code != 0
    assert "not found" in result.output.lower()
