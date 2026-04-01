"""Flask CLI-Befehle für X2FA-Administration."""

import secrets
import click
from flask import current_app
from flask.cli import with_appcontext

from app.extensions import db
from app.models import (
    AuditLog, BackupCode, Credential, OIDCClient,
    SigningKey, TOTPSecret,
)


@click.command("init-keys")
@with_appcontext
def init_keys():
    """Generiert EC P-256 Signing-Key für ID-Token (ES256)."""
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import (
        Encoding, NoEncryption, PublicFormat, PrivateFormat,
    )
    from app.services.crypto import CryptoService

    crypto = CryptoService(current_app.config["X2FA_SECRET"])

    private_key = ec.generate_private_key(ec.SECP256R1())
    public_key  = private_key.public_key()

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

    # Alle bestehenden Keys deaktivieren
    SigningKey.query.update({"active": False})

    db.session.add(SigningKey(
        kid=kid,
        private_key_encrypted=private_encrypted,
        public_key_pem=public_pem,
        algorithm="ES256",
        active=True,
    ))
    db.session.commit()
    click.echo(f"Signing-Key generiert: kid={kid}")


@click.command("add-client")
@click.argument("client_id")
@click.argument("redirect_uri")
@click.option("--secret", default=None, help="Client-Secret (wird generiert wenn leer)")
@click.option("--scopes", default="openid x2fa:setup", show_default=True)
@with_appcontext
def add_client(client_id, redirect_uri, secret, scopes):
    """Registriert einen neuen OIDC-Client."""
    if not secret:
        secret = secrets.token_urlsafe(32)

    existing = OIDCClient.query.get(client_id)
    if existing:
        click.echo(f"Client '{client_id}' existiert bereits. Überschreibe redirect_uri.", err=True)
        existing.redirect_uris = redirect_uri
        existing.allowed_scopes = scopes
    else:
        db.session.add(OIDCClient(
            client_id=client_id,
            client_secret=secret,
            redirect_uris=redirect_uri,
            allowed_scopes=scopes,
        ))

    db.session.commit()
    click.echo(f"Client-ID:     {client_id}")
    click.echo(f"Client-Secret: {secret}")
    click.echo(f"Redirect-URI:  {redirect_uri}")
    click.echo(f"Scopes:        {scopes}")


@click.command("list-clients")
@with_appcontext
def list_clients():
    """Listet alle registrierten OIDC-Clients."""
    clients = OIDCClient.query.all()
    if not clients:
        click.echo("Keine Clients registriert.")
        return
    for c in clients:
        status = "aktiv" if c.active else "deaktiviert"
        click.echo(f"  {c.client_id:30s} [{status}]  {c.redirect_uris[:60]}")


@click.command("revoke-client")
@click.argument("client_id")
@with_appcontext
def revoke_client(client_id):
    """Deaktiviert einen OIDC-Client."""
    client = OIDCClient.query.get(client_id)
    if not client:
        click.echo(f"Client '{client_id}' nicht gefunden.", err=True)
        return
    client.active = False
    db.session.commit()
    click.echo(f"Client '{client_id}' deaktiviert.")


@click.command("stats")
@with_appcontext
def stats():
    """Zeigt Nutzungsstatistiken."""
    from sqlalchemy import func
    rows = (
        db.session.query(AuditLog.action, AuditLog.method, func.count())
        .group_by(AuditLog.action, AuditLog.method)
        .all()
    )
    click.echo("Audit-Statistiken:")
    for action, method, count in rows:
        click.echo(f"  {action:8s} {method:25s} {count:5d}x")

    click.echo(f"\nCredentials:  {Credential.query.count()}")
    click.echo(f"TOTP-Secrets: {TOTPSecret.query.count()}")
    click.echo(f"Backup-Codes: {BackupCode.query.filter(BackupCode.used_at.is_(None)).count()} verbleibend")


@click.command("cleanup-codes")
@with_appcontext
def cleanup_codes():
    """Bereinigt Authorization Codes älter als 1 Stunde (Nonce-Schutz bleibt erhalten)."""
    from datetime import datetime, timezone, timedelta
    from app.models import AuthorizationCode

    cutoff = datetime.now(timezone.utc) - timedelta(hours=1)
    old = AuthorizationCode.query.filter(AuthorizationCode.expires_at < cutoff).all()
    count = len(old)
    for code in old:
        db.session.delete(code)
    db.session.commit()
    click.echo(f"Gelöscht: {count} Authorization Codes (älter als 1 Stunde).")


def register_commands(app):
    app.cli.add_command(init_keys)
    app.cli.add_command(add_client)
    app.cli.add_command(list_clients)
    app.cli.add_command(revoke_client)
    app.cli.add_command(stats)
    app.cli.add_command(cleanup_codes)
