"""Unit tests for Flask CLI commands."""

import pytest
import os

from x2fa.app import create_app
from x2fa.models import OIDCClient, SigningKey
from x2fa.init_app.database import db


def test_add_client_new():
    """Adds a new client successfully via CLI."""
    from flask.cli import FlaskGroup
    from click.testing import CliRunner

    runner = CliRunner()
    cli = FlaskGroup(create_app=create_app)

    result = runner.invoke(
        cli, ["add-client", "test-client", "https://example.com/callback"]
    )

    assert result.exit_code == 0, f"Command failed: {result.output}"
    assert "Client ID:     test-client" in result.output
    assert "Client secret:" in result.output
    assert "Redirect URI:  https://example.com/callback" in result.output


def test_add_client_existing_updates():
    """Updates existing client when adding duplicate."""
    from flask.cli import FlaskGroup
    from click.testing import CliRunner
    from x2fa.models import OIDCClient
    from x2fa.init_app.database import db

    runner = CliRunner()
    cli = FlaskGroup(create_app=create_app)

    # First add
    result1 = runner.invoke(
        cli, ["add-client", "demo-rp-updated", "https://old.callback.url/cb"]
    )
    assert result1.exit_code == 0

    result1 = runner.invoke(
        cli, ["add-client", "demo-rp-updated", "https://old.callback.url/cb"]
    )
    assert result1.exit_code == 0

    with create_app().app_context():
        with db.session_scope() as db_session:
            client_obj = (
                db_session.query(OIDCClient)
                .filter_by(client_id="demo-rp-updated")
                .first()
            )
            old_secret = client_obj.client_secret
            old_uri = client_obj.redirect_uris

            result2 = runner.invoke(
                cli, ["add-client", "demo-rp-updated", "https://new.callback.url/cb"]
            )

            assert result2.exit_code == 0
            assert "already exists" in result2.output.lower()

            client_obj = (
                db_session.query(OIDCClient)
                .filter_by(client_id="demo-rp-updated")
                .first()
            )
            assert client_obj.redirect_uris == "https://new.callback.url/cb"
            assert client_obj.client_secret != old_secret


def test_add_client_custom_secret():
    """Adds client with custom secret."""
    from flask.cli import FlaskGroup
    from click.testing import CliRunner

    runner = CliRunner()
    cli = FlaskGroup(create_app=create_app)

    result = runner.invoke(
        cli,
        [
            "add-client",
            "custom-client",
            "https://example.com/callback",
            "--secret",
            "my-custom-secret-123",
        ],
    )

    assert result.exit_code == 0
    assert "Client secret: my-custom-secret-123" in result.output


def test_add_client_custom_scopes():
    """Adds client with custom scopes."""
    from flask.cli import FlaskGroup
    from click.testing import CliRunner

    runner = CliRunner()
    cli = FlaskGroup(create_app=create_app)

    result = runner.invoke(
        cli,
        [
            "add-client",
            "scope-client",
            "https://example.com/callback",
            "--scopes",
            "openid profile email",
        ],
    )

    assert result.exit_code == 0
    assert "Scopes:        openid profile email" in result.output


def test_list_clients_empty():
    """Lists clients when none exist."""
    from flask.cli import FlaskGroup
    from click.testing import CliRunner
    from x2fa.init_app.database import db

    # Ensure clean DB state
    with create_app().app_context():
        with db.session_scope() as db_session:
            db_session.query(OIDCClient).delete()

    runner = CliRunner()
    cli = FlaskGroup(create_app=create_app)

    result = runner.invoke(cli, ["list-clients"])

    assert result.exit_code == 0
    assert "No clients registered." in result.output


def test_list_clients_shows_registered():
    """Lists registered clients."""
    from flask.cli import FlaskGroup
    from click.testing import CliRunner

    runner = CliRunner()
    cli = FlaskGroup(create_app=create_app)

    runner.invoke(cli, ["add-client", "client1", "https://example.com/cb1"])
    runner.invoke(cli, ["add-client", "client2", "https://example.com/cb2"])

    result = runner.invoke(cli, ["list-clients"])

    assert result.exit_code == 0
    assert "client1" in result.output
    assert "client2" in result.output


def test_revoke_client_exists():
    """Deactivates existing client."""
    from flask.cli import FlaskGroup
    from click.testing import CliRunner
    from x2fa.models import OIDCClient
    from x2fa.init_app.database import db

    runner = CliRunner()
    cli = FlaskGroup(create_app=create_app)

    runner.invoke(cli, ["add-client", "to-revoke", "https://example.com/cb"])

    result = runner.invoke(cli, ["revoke-client", "to-revoke"])

    assert result.exit_code == 0
    assert "deactivated" in result.output

    with create_app().app_context():
        with db.session_scope() as db_session:
            client_obj = (
                db_session.query(OIDCClient).filter_by(client_id="to-revoke").first()
            )
            assert client_obj.active is False


def test_revoke_client_not_found():
    """Handles revoking non-existent client."""
    from flask.cli import FlaskGroup
    from click.testing import CliRunner

    runner = CliRunner()
    cli = FlaskGroup(create_app=create_app)

    result = runner.invoke(cli, ["revoke-client", "nonexistent"])

    assert result.exit_code == 0
    assert "not found" in result.output.lower()


def test_init_keys_generates_key():
    """Initializes signing keys."""
    from flask.cli import FlaskGroup
    from click.testing import CliRunner
    from x2fa.models import SigningKey
    from x2fa.init_app.database import db

    runner = CliRunner()
    cli = FlaskGroup(create_app=create_app)

    result = runner.invoke(cli, ["init-keys"])

    assert result.exit_code == 0
    assert "Signing key generated" in result.output

    with create_app().app_context():
        with db.session_scope() as db_session:
            keys = db_session.query(SigningKey).all()
            assert len(keys) == 1
            assert keys[0].active is True
            assert keys[0].algorithm == "ES256"
