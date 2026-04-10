"""Flask CLI commands for X2FA administration."""

import secrets
import click
from flask import current_app
from flask.cli import with_appcontext

from sqlalchemy import update

from x2fa.constants import NEVER_USED
from x2fa.models import (
    AuditLog,
    BackupCode,
    Credential,
    OIDCClient,
    SigningKey,
    TOTPSecret,
)

from x2fa.init_app.database import SessionFactory


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

    db_session = SessionFactory()

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

    # Deactivate all existing keys

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
    db_session.commit()
    click.echo(f"Signing key generated: kid={kid}")


@click.command("add-client")
@click.argument("client_id")
@click.argument("redirect_uri")
@click.option(
    "--secret", default=None, help="Client secret (generated automatically if empty)"
)
@click.option("--scopes", default="openid app:setup", show_default=True)
@with_appcontext
def add_client(client_id, redirect_uri, secret, scopes):
    """Registers a new OIDC client."""
    if not secret:
        secret = secrets.token_urlsafe(32)

    db_session = SessionFactory()

    existing = db_session.get(OIDCClient, client_id)
    if existing:
        click.echo(
            f"Client '{client_id}' already exists. Updating configuration.", err=True
        )
        existing.redirect_uris = redirect_uri
        existing.allowed_scopes = scopes
        existing.client_secret = (
            secret  # always update (new random or explicitly given)
        )
    else:
        db_session.add(
            OIDCClient(
                client_id=client_id,
                client_secret=secret,
                redirect_uris=redirect_uri,
                allowed_scopes=scopes,
            )
        )

    db_session.commit()
    click.echo(f"Client ID:     {client_id}")
    click.echo(f"Client secret: {secret}")
    click.echo(f"Redirect URI:  {redirect_uri}")
    click.echo(f"Scopes:        {scopes}")


@click.command("list-clients")
@with_appcontext
def list_clients():
    """Lists all registered OIDC clients."""
    stmt = select(OIDCClient)
    clients = g.db_session.execute(stmt).scalars().all()
    if not clients:
        click.echo("No clients registered.")
        return
    for c in clients:
        status = "active" if c.active else "deactivated"
        click.echo(f"  {c.client_id:30s} [{status}]  {c.redirect_uris[:60]}")


@click.command("revoke-client")
@click.argument("client_id")
@with_appcontext
def revoke_client(client_id):
    """Deactivates an OIDC client."""

    db_session = SessionFactory()

    client = db_session.get(OIDCClient, client_id)
    if not client:
        click.echo(f"Client '{client_id}' not found.", err=True)
        return
    client.active = False
    db_session.commit()
    click.echo(f"Client '{client_id}' deactivated.")


@click.command("stats")
@with_appcontext
def stats():
    """Shows usage statistics."""
    from sqlalchemy import func

    db_session = SessionFactory()

    stmt = select(AuditLog.action, AuditLog.method, func.count()).group_by(
        AuditLog.action, AuditLog.method
    )
    rows = db_session.execute(stmt).all()
    click.echo("Audit statistics:")
    for action, method, count in rows:
        click.echo(f"  {action:8s} {method:25s} {count:5d}x")

    stmt = select(func.count()).select_from(Credential)
    count = g.db_session.execute(stmt).scalar()
    click.echo(f"\nCredentials:  {count}")

    stmt = select(func.count()).select_from(TOTPSecret)
    count = g.db_session.execute(stmt).scalar()
    click.echo(f"TOTP secrets: {count}")

    stmt = (
        select(func.count())
        .select_from(BackupCode)
        .where(BackupCode.used_at == NEVER_USED)
    )
    count = g.db_session.execute(stmt).scalar()
    click.echo(f"Backup codes: {count} remaining")


@click.command("cleanup-codes")
@with_appcontext
def cleanup_codes():
    """Removes authorization codes older than 1 hour (nonce protection is preserved)."""
    from datetime import datetime, timezone, timedelta
    from x2fa.models import AuthorizationCode

    db_session = SessionFactory()

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    stmt = select(AuthorizationCode).where(AuthorizationCode.expires_at < cutoff)
    old = g.db_session.execute(stmt).scalars().all()
    count = len(old)
    for code in old:
        db_session.delete(code)
    db_session.commit()
    click.echo(f"Deleted: {count} authorization codes (older than 1 hour).")


def register_commands(app):
    app.cli.add_command(init_keys)
    app.cli.add_command(add_client)
    app.cli.add_command(list_clients)
    app.cli.add_command(revoke_client)
    app.cli.add_command(stats)
    app.cli.add_command(cleanup_codes)
