"""Tests for add-client / list-clients CLI and OIDCClient auth method logic."""

import pytest
from flask.cli import FlaskGroup
from click.testing import CliRunner
from sqlalchemy import select

from x2fa.app import create_app
from x2fa.model import OIDCClient
from x2fa.init_app.database import db


def _cli():
    return FlaskGroup(create_app=create_app)


def _get_client(client_id):
    """Returns a plain dict of OIDCClient fields (safe to use outside session)."""
    with create_app().app_context():
        with db.session_scope() as session:
            c = session.execute(
                select(OIDCClient).where(OIDCClient.client_id == client_id)
            ).scalars().first()
            if c is None:
                return None
            return {
                "client_id": c.client_id,
                "client_secret": c.client_secret,
                "token_endpoint_auth_method": c.token_endpoint_auth_method,
                "jwks_uri": c.jwks_uri,
                "active": c.active,
            }


# ---------------------------------------------------------------------------
# add-client --method
# ---------------------------------------------------------------------------

def test_add_client_default_method_generates_secret():
    """Default method is client_secret_post and a secret is auto-generated."""
    runner = CliRunner()
    result = runner.invoke(_cli(), ["add-client", "rp-default", "https://rp/cb"])

    assert result.exit_code == 0, result.output
    assert "Auth method:   client_secret_post" in result.output
    assert "Client secret:" in result.output

    client = _get_client("rp-default")
    assert client["token_endpoint_auth_method"] == "client_secret_post"
    assert client["client_secret"] != ""


def test_add_client_tls_auth_stores_no_secret():
    """tls_client_auth stores an empty secret and no secret is printed."""
    runner = CliRunner()
    result = runner.invoke(
        _cli(), ["add-client", "rp-mtls", "https://rp/cb", "--method", "tls_client_auth"]
    )

    assert result.exit_code == 0, result.output
    assert "Auth method:   tls_client_auth" in result.output
    assert "Client secret:" not in result.output

    client = _get_client("rp-mtls")
    assert client["token_endpoint_auth_method"] == "tls_client_auth"
    assert client["client_secret"] == ""


def test_add_client_private_key_jwt_requires_jwks_uri():
    """private_key_jwt without --jwks-uri is rejected."""
    runner = CliRunner()
    result = runner.invoke(
        _cli(), ["add-client", "rp-jwt", "https://rp/cb", "--method", "private_key_jwt"]
    )

    assert result.exit_code != 0
    assert "jwks-uri" in result.output.lower()


def test_add_client_private_key_jwt_stores_jwks_uri():
    """private_key_jwt with --jwks-uri stores the URI and no secret."""
    runner = CliRunner()
    result = runner.invoke(
        _cli(),
        [
            "add-client", "rp-jwt", "https://rp/cb",
            "--method", "private_key_jwt",
            "--jwks-uri", "https://rp/.well-known/jwks.json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "JWKS URI:" in result.output
    assert "Client secret:" not in result.output

    client = _get_client("rp-jwt")
    assert client["token_endpoint_auth_method"] == "private_key_jwt"
    assert client["jwks_uri"] == "https://rp/.well-known/jwks.json"
    assert client["client_secret"] == ""


# ---------------------------------------------------------------------------
# list-clients shows auth method
# ---------------------------------------------------------------------------

def test_list_clients_shows_auth_method():
    """list-clients output includes the token_endpoint_auth_method column."""
    runner = CliRunner()
    runner.invoke(
        _cli(),
        ["add-client", "rp-show", "https://rp/cb", "--method", "tls_client_auth"],
    )

    result = runner.invoke(_cli(), ["list-clients"])

    assert result.exit_code == 0, result.output
    assert "tls_client_auth" in result.output


# ---------------------------------------------------------------------------
# check_token_endpoint_auth_method
# ---------------------------------------------------------------------------

def test_check_token_endpoint_auth_method_matches_registered():
    """Returns True only for the method stored on the client row."""
    client = OIDCClient(
        client_id="rp-check",
        client_secret="",
        redirect_uris="https://rp/cb",
        token_endpoint_auth_method="tls_client_auth",
    )
    assert client.check_token_endpoint_auth_method("tls_client_auth") is True
    assert client.check_token_endpoint_auth_method("client_secret_post") is False
    assert client.check_token_endpoint_auth_method("private_key_jwt") is False
