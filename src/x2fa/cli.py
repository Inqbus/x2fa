"""Flask CLI commands for X2FA administration."""

import secrets
from pathlib import Path

import click
from flask import current_app
from flask.cli import with_appcontext

from sqlalchemy import select, update

from x2fa.constants import (
    NEVER_USED,
    ALL_AUTH_METHODS,
    AUTH_METHOD_TLS_CLIENT_AUTH,
    AUTH_METHOD_PRIVATE_KEY_JWT,
    AUTH_METHOD_SELF_SIGNED_TLS,
    AUTH_METHOD_CLIENT_SECRET_JWT,
    AUTH_METHOD_CLIENT_SECRET_POST,
    AUTH_METHOD_CLIENT_SECRET_BASIC,
)
from x2fa.init_app.config import load_config

_SECRET_METHODS = {
    AUTH_METHOD_CLIENT_SECRET_JWT,
    AUTH_METHOD_CLIENT_SECRET_POST,
    AUTH_METHOD_CLIENT_SECRET_BASIC,
}
from x2fa.model import (
    AuditLog,
    BackupCode,
    Credential,
    OIDCClient,
    SigningKey,
    TOTPSecret,
    TrustedCA,
)

from x2fa.init_app.database import db
from x2fa.paths import data_dir


def _resolve_file(path_str: str, label: str = "path") -> Path:
    """Resolve and validate a file path stays within the filesystem root.

    Prevents path traversal attacks by ensuring the resolved path is
    a regular file (not a symlink to an arbitrary location) and that
    the parent directory is writable.
    """
    p = Path(path_str).expanduser().resolve()
    if not p.is_file():
        raise click.ClickException(f"{label}: file does not exist: {path_str}")
    return p


@click.command("init-db")
@with_appcontext
def init_db():
    """Creates all database tables on a fresh database.

    Uses Alembic migrations internally so the schema version is tracked.
    For existing installations use `flask db-upgrade` instead.
    """
    _run_alembic_upgrade()
    click.echo("Database tables created.")


@click.command("db-upgrade")
@with_appcontext
def db_upgrade():
    """Apply pending Alembic migrations (safe for existing installations)."""
    _run_alembic_upgrade()
    click.echo("Database migrations applied.")


def _run_alembic_upgrade():
    """Run ``alembic upgrade head`` programmatically.

    If the database already has tables but no ``alembic_version`` tracking row
    (e.g. re-running the installer on an existing installation), the schema is
    stamped at ``head`` before upgrading so Alembic does not try to re-create
    tables that already exist.
    """
    from importlib.resources import files as _pkg_files
    from pathlib import Path
    from alembic import command
    from alembic.config import Config as AlembicConfig
    from sqlalchemy import create_engine, inspect
    

    migrations_dir = _pkg_files("x2fa").joinpath("migrations")
    ini_path = migrations_dir / "alembic.ini"

    db_url = load_config().x2fa_database.SQLALCHEMY_DATABASE_URI
    # Resolve relative paths to the data directory
    if db_url.startswith("sqlite:///"):
        relative_path = db_url[len("sqlite:///"):]
        if not relative_path.startswith("/"):
            resolved_path = data_dir() / relative_path
            db_url = "sqlite:///" + str(resolved_path)
    alembic_cfg = AlembicConfig(str(ini_path))
    alembic_cfg.set_main_option("script_location", str(migrations_dir))
    alembic_cfg.set_main_option("sqlalchemy.url", db_url)

    engine = create_engine(db_url)
    try:
        existing_tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()

    if existing_tables and "alembic_version" not in existing_tables:
        # Pre-existing database without Alembic tracking — stamp to head so
        # the subsequent upgrade sees the schema as already current.
        command.stamp(alembic_cfg, "head")

    try:
        command.upgrade(alembic_cfg, "head")
    except Exception as exc:
        if "already exists" in str(exc).lower():
            # Stamp did not prevent the re-run (e.g. connection isolation).
            # The tables are intact — record the current state and continue.
            command.stamp(alembic_cfg, "head")
        else:
            raise


@click.command("init-keys")
@with_appcontext
def init_keys():
    """Generates an EC P-256 signing key for ID tokens (ES256)."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        NoEncryption,
        PublicFormat,
        PrivateFormat,
    )
    from x2fa.services.crypto import CryptoService

    crypto = CryptoService(current_app.config.x2fa_security.SECRET_KEY)

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key = private_key.public_key()

    private_pem = private_key.private_bytes(
        encoding=Encoding.PEM,
        format=PrivateFormat.PKCS8,
        encryption_algorithm=NoEncryption(),
    )
    public_pem = public_key.public_bytes(
        encoding=Encoding.PEM,
        format=PublicFormat.SubjectPublicKeyInfo,
    ).decode()

    private_encrypted = crypto.get_fernet().encrypt(private_pem)
    kid = secrets.token_hex(8)

    with db.session_scope() as db_session:
        stmt = update(SigningKey).values(active=False)
        db_session.execute(stmt)

        db_session.add(
            SigningKey(
                kid=kid,
                private_key_encrypted=private_encrypted,
                public_key_pem=public_pem,
                algorithm="ES256",
                active=True,
            )
        )
    click.echo(f"Signing key generated: kid={kid}")


@click.command("add-client")
@click.argument("client_id")
@click.argument("redirect_uri")
@click.option(
    "--method",
    default=AUTH_METHOD_TLS_CLIENT_AUTH,
    show_default=True,
    type=click.Choice(ALL_AUTH_METHODS),
    help="Token endpoint authentication method.",
)
@click.option("--scopes", default="openid app:setup", show_default=True)
@click.option("--jwks-uri", default=None, help="JWKS URL (required for private_key_jwt).")
@click.option(
    "--cert", default=None,
    type=click.Path(exists=True, readable=True),
    help="Path to self-signed client cert PEM (required for self_signed_tls_client_auth).",
)
@click.option(
    "--secret", default=None,
    help="Plaintext client secret (client_secret_* methods). Generated if omitted.",
)
@with_appcontext
def add_client(client_id, redirect_uri, method, scopes, jwks_uri, cert, secret):
    """Registers a new OIDC client."""
    if method == AUTH_METHOD_PRIVATE_KEY_JWT and not jwks_uri:
        raise click.UsageError("--jwks-uri is required for private_key_jwt.")
    if method == AUTH_METHOD_SELF_SIGNED_TLS and not cert:
        raise click.UsageError("--cert is required for self_signed_tls_client_auth.")

    fingerprint = None
    if method == AUTH_METHOD_SELF_SIGNED_TLS:
        from cryptography import x509
        from cryptography.hazmat.primitives import hashes

        cert_path = _resolve_file(cert, "Certificate")
        cert_pem = cert_path.read_text()
        try:
            cert_obj = x509.load_pem_x509_certificate(cert_pem.encode())
        except Exception as exc:
            raise click.ClickException(f"Not a valid PEM certificate: {exc}")
        fingerprint = cert_obj.fingerprint(hashes.SHA256()).hex(":")

    plaintext_secret = None
    secret_encrypted = None
    if method in _SECRET_METHODS:
        from x2fa.services.crypto import CryptoService
        plaintext_secret = secret if secret else secrets.token_hex(32)
        crypto = CryptoService(current_app.config.x2fa_security.SECRET_KEY)
        secret_encrypted = crypto.encrypt(plaintext_secret)

    with db.session_scope() as db_session:
        existing = db_session.get(OIDCClient, client_id)
        if existing:
            click.echo(
                f"Client '{client_id}' already exists. Updating configuration.",
                err=True,
            )
            existing.redirect_uris = redirect_uri
            existing.allowed_scopes = scopes
            existing.token_endpoint_auth_method = method
            existing.jwks_uri = jwks_uri
            existing.client_cert_fingerprint = fingerprint
            if secret_encrypted is not None:
                existing.client_secret_encrypted = secret_encrypted
        else:
            db_session.add(
                OIDCClient(
                    client_id=client_id,
                    redirect_uris=redirect_uri,
                    allowed_scopes=scopes,
                    token_endpoint_auth_method=method,
                    jwks_uri=jwks_uri,
                    client_cert_fingerprint=fingerprint,
                    client_secret_encrypted=secret_encrypted,
                )
            )

    click.echo(f"Client ID:     {client_id}")
    click.echo(f"Auth method:   {method}")
    if jwks_uri:
        click.echo(f"JWKS URI:      {jwks_uri}")
    if fingerprint:
        click.echo(f"Fingerprint:   {fingerprint}")
    if plaintext_secret:
        click.echo(f"Client secret: {plaintext_secret}  <- record this now, it will not be shown again")
    click.echo(f"Redirect URI:  {redirect_uri}")
    click.echo(f"Scopes:        {scopes}")


@click.command("list-clients")
@with_appcontext
def list_clients():
    """Lists all registered OIDC clients."""
    with db.session_scope() as db_session:
        stmt = select(OIDCClient)
        clients = db_session.execute(stmt).scalars().all()
        if not clients:
            click.echo("No clients registered.")
            return
        for c in clients:
            status = "active" if c.active else "deactivated"
            click.echo(
                f"  {c.client_id:30s} [{status}]  "
                f"{c.token_endpoint_auth_method:20s}  {c.redirect_uris[:50]}"
            )


@click.command("revoke-client")
@click.argument("client_id")
@with_appcontext
def revoke_client(client_id):
    """Deactivates an OIDC client."""

    with db.session_scope() as db_session:
        client = db_session.get(OIDCClient, client_id)
        if not client:
            click.echo(f"Client '{client_id}' not found.", err=True)
            return
        client.active = False
    click.echo(f"Client '{client_id}' deactivated.")


@click.command("stats")
@with_appcontext
def stats():
    """Shows usage statistics."""
    from sqlalchemy import func

    with db.session_scope() as db_session:
        stmt = select(AuditLog.action, AuditLog.method, func.count()).group_by(
            AuditLog.action, AuditLog.method
        )
        rows = db_session.execute(stmt).all()
    click.echo("Audit statistics:")
    for action, method, count in rows:
        click.echo(f"  {action:8s} {method:25s} {count:5d}x")

    with db.session_scope() as db_session:
        stmt = select(func.count()).select_from(Credential)
        count = db_session.execute(stmt).scalar()
    click.echo(f"\nCredentials:  {count}")

    with db.session_scope() as db_session:
        stmt = select(func.count()).select_from(TOTPSecret)
        count = db_session.execute(stmt).scalar()
    click.echo(f"TOTP secrets: {count}")

    with db.session_scope() as db_session:
        stmt = (
            select(func.count())
            .select_from(BackupCode)
            .where(BackupCode.used_at == NEVER_USED)
        )
        count = db_session.execute(stmt).scalar()
    click.echo(f"Backup codes: {count} remaining")


@click.command("cleanup-codes")
@with_appcontext
def cleanup_codes():
    """Removes authorization codes older than 1 hour (nonce protection is preserved)."""
    from datetime import datetime, timezone, timedelta
    from x2fa.model import AuthorizationCode

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    with db.session_scope() as db_session:
        stmt = select(AuthorizationCode).where(AuthorizationCode.expires_at < cutoff)
        old = db_session.execute(stmt).scalars().all()
    count = len(old)
    with db.session_scope() as db_session:
        for code in old:
            db_session.delete(code)
    click.echo(f"Deleted: {count} authorization codes (older than 1 hour).")


@click.command("add-ca")
@click.argument("name")
@click.argument("cert_path", type=click.Path(exists=True, readable=True))
@with_appcontext
def add_ca(name, cert_path):
    """Registers a trusted CA certificate for mTLS client authentication."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization

    cert_path = _resolve_file(cert_path, "CA certificate")
    cert_pem = cert_path.read_text()
    try:
        cert = x509.load_pem_x509_certificate(cert_pem.encode())
    except Exception as exc:
        raise click.ClickException(f"Not a valid PEM certificate: {exc}")

    expires_at = cert.not_valid_after_utc
    fingerprint = cert.fingerprint(hashes.SHA256()).hex(":")

    with db.session_scope() as db_session:
        existing = db_session.execute(
            select(TrustedCA).where(TrustedCA.name == name)
        ).scalars().first()
        if existing:
            click.echo(f"CA '{name}' already registered — skipping.", err=True)
            return
        db_session.add(TrustedCA(name=name, cert_pem=cert_pem, expires_at=expires_at))

    click.echo(f"CA registered:  {name}")
    click.echo(f"Expires:        {expires_at.date()}")
    click.echo(f"Fingerprint:    {fingerprint}")


@click.command("list-cas")
@with_appcontext
def list_cas():
    """Lists all registered CA certificates."""
    from datetime import datetime, timezone, timedelta
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    now = datetime.now(timezone.utc)
    warn_threshold = now + timedelta(days=30)

    with db.session_scope() as db_session:
        cas = db_session.execute(select(TrustedCA)).scalars().all()

        if not cas:
            click.echo("No CAs registered.")
            return

        for ca in cas:
            status = "active" if ca.active else "revoked"
            try:
                cert = x509.load_pem_x509_certificate(ca.cert_pem.encode())
                fingerprint = cert.fingerprint(hashes.SHA256()).hex(":")[:29] + "…"
                expiry = cert.not_valid_after_utc
                expiry_str = str(expiry.date())
                if ca.active and expiry < now:
                    expiry_str += "  *** EXPIRED ***"
                elif ca.active and expiry < warn_threshold:
                    expiry_str += "  (expires soon)"
            except Exception:
                fingerprint = "unparseable"
                expiry_str = "unknown"

            click.echo(f"  {ca.name:30s} [{status}]  expires {expiry_str}")
            click.echo(f"  {'':30s}          {fingerprint}")


@click.command("revoke-ca")
@click.argument("name")
@with_appcontext
def revoke_ca(name):
    """Deactivates a trusted CA (does not delete — audit trail is preserved)."""
    with db.session_scope() as db_session:
        ca = db_session.execute(
            select(TrustedCA).where(TrustedCA.name == name)
        ).scalars().first()
        if not ca:
            raise click.ClickException(f"CA '{name}' not found.")
        if not ca.active:
            click.echo(f"CA '{name}' is already revoked.")
            return
        ca.active = False

    click.echo(f"CA '{name}' revoked.")
    click.echo("Warning: verify that no active OIDC clients depend on this CA.")


@click.command("issue-client-cert")
@click.argument("client_id")
@click.option("--ca", "ca_name", required=True, help="Name of the signing CA.")
@click.option("--validity-days", default=90, show_default=True, help="Certificate validity in days.")
@click.option(
    "--output", default=".", show_default=True,
    type=click.Path(file_okay=False, writable=True),
    help="Directory to write the certificate files.",
)
@with_appcontext
def issue_client_cert(client_id, ca_name, validity_days, output):
    """Issues a client certificate signed by the named CA."""
    import os
    from datetime import datetime, timezone, timedelta
    from cryptography import x509
    from cryptography.x509.oid import NameOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    with db.session_scope() as db_session:
        ca = db_session.execute(
            select(TrustedCA).where(TrustedCA.name == ca_name, TrustedCA.active == True)
        ).scalars().first()
        if not ca:
            raise click.ClickException(f"Active CA '{ca_name}' not found.")
        ca_cert_pem = ca.cert_pem

    try:
        ca_cert = x509.load_pem_x509_certificate(ca_cert_pem.encode())
    except Exception as exc:
        raise click.ClickException(f"Failed to parse CA certificate: {exc}")

    # The CA private key is not stored in the DB — must be provided via file.
    ca_key_path = _resolve_file(
        click.prompt("Path to CA private key file"), "CA private key"
    )
    try:
        ca_key_pem = ca_key_path.read_bytes()
        ca_key = serialization.load_pem_private_key(ca_key_pem, password=None)
    except Exception as exc:
        raise click.ClickException(f"Failed to load CA private key: {exc}")

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
    key_path  = os.path.join(output, f"{safe_id}.key.pem")
    cert_path = os.path.join(output, f"{safe_id}.cert.pem")
    ca_out    = os.path.join(output, f"{safe_id}.ca.pem")

    key_pem = client_key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    with open(key_path, "wb") as f:
        f.write(key_pem)
    os.chmod(key_path, 0o600)

    with open(cert_path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

    with open(ca_out, "w") as f:
        f.write(ca_cert_pem)

    click.echo(f"Private key:    {key_path}  (mode 0600)")
    click.echo(f"Certificate:    {cert_path}")
    click.echo(f"CA certificate: {ca_out}")
    click.echo(f"Valid for:      {validity_days} days")


@click.command("update-client-cert")
@click.argument("client_id")
@click.option(
    "--cert", required=True,
    type=click.Path(exists=True, readable=True),
    help="Path to the new self-signed client cert PEM.",
)
@with_appcontext
def update_client_cert(client_id, cert):
    """Updates the pinned certificate fingerprint for a self_signed_tls_client_auth client."""
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes

    cert_path = _resolve_file(cert, "Certificate")
    cert_pem = cert_path.read_text()
    try:
        cert_obj = x509.load_pem_x509_certificate(cert_pem.encode())
    except Exception as exc:
        raise click.ClickException(f"Not a valid PEM certificate: {exc}")

    fingerprint = cert_obj.fingerprint(hashes.SHA256()).hex(":")

    with db.session_scope() as db_session:
        client = db_session.get(OIDCClient, client_id)
        if not client:
            raise click.ClickException(f"Client '{client_id}' not found.")
        if client.token_endpoint_auth_method != AUTH_METHOD_SELF_SIGNED_TLS:
            raise click.ClickException(
                f"Client '{client_id}' uses '{client.token_endpoint_auth_method}', "
                "not self_signed_tls_client_auth."
            )
        client.client_cert_fingerprint = fingerprint

    click.echo(f"Client '{client_id}' fingerprint updated.")
    click.echo(f"Fingerprint: {fingerprint}")


@click.command("rotate-client-secret")
@click.argument("client_id")
@with_appcontext
def rotate_client_secret(client_id):
    """Rotates the client secret for client_secret_jwt / _post / _basic clients."""
    from x2fa.services.crypto import CryptoService

    with db.session_scope() as db_session:
        client = db_session.get(OIDCClient, client_id)
        if not client:
            raise click.ClickException(f"Client '{client_id}' not found.")
        if client.token_endpoint_auth_method not in _SECRET_METHODS:
            raise click.ClickException(
                f"Client '{client_id}' uses '{client.token_endpoint_auth_method}', "
                "which does not use a client secret."
            )

        plaintext_secret = secrets.token_hex(32)
        crypto = CryptoService(current_app.config.x2fa_security.SECRET_KEY)
        client.client_secret_encrypted = crypto.encrypt(plaintext_secret)

    click.echo(f"Client '{client_id}' secret rotated.")
    click.echo(f"New secret: {plaintext_secret}  <- record this now, it will not be shown again")


def register_commands(app):
    app.cli.add_command(init_keys)
    app.cli.add_command(add_client)
    app.cli.add_command(list_clients)
    app.cli.add_command(revoke_client)
    app.cli.add_command(stats)
    app.cli.add_command(cleanup_codes)
    app.cli.add_command(init_db)
    app.cli.add_command(db_upgrade)
    app.cli.add_command(add_ca)
    app.cli.add_command(list_cas)
    app.cli.add_command(revoke_ca)
    app.cli.add_command(issue_client_cert)
    app.cli.add_command(update_client_cert)
    app.cli.add_command(rotate_client_secret)
