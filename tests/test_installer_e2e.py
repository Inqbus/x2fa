"""End-to-end tests for the installer — drives all screens like a real user
and verifies the generated config file contents afterwards."""

import tomllib
from pathlib import Path
from unittest.mock import patch

import pytest
from textual.widgets import Input

from installer.app import InstallerApp

_SIZE = (120, 60)

_ALL_OK_CHECKS = [
    {"label": "Running as x2fa",    "ok": True, "blocking": False},
    {"label": "Python ≥ 3.11",      "ok": True, "blocking": True},
    {"label": "uv package manager", "ok": True, "blocking": True},
    {"label": "Port 5000 free",     "ok": True, "blocking": False},
    {"label": "Redis reachable",    "ok": True, "blocking": False},
]


def _read_toml(tmp_path: Path, filename: str) -> dict:
    return tomllib.loads((tmp_path / ".config" / "x2fa" / filename).read_text())


async def _wait_for_screen_change(pilot, app, expected_screen_prefix: str, timeout: float = 5.0):
    """Wait for the app screen to change to one matching expected_screen_prefix.
    
    Polls every 0.1s for up to timeout seconds, returning when the screen class
    name starts with the expected prefix (e.g. "SummaryScreen" matches "Summary").
    """
    import time
    start = time.time()
    while time.time() - start < timeout:
        current = app.screen.__class__.__name__
        if current.startswith(expected_screen_prefix):
            return current
        await pilot.pause(0.1)
    raise AssertionError(
        f"Screen never changed to {expected_screen_prefix}. "
        f"Final screen: {app.screen.__class__.__name__}"
    )


async def _wait_for_screen(pilot, app, expected_screen_class: type):
    """Wait for the app screen to change to the expected screen class."""
    import time
    start = time.time()
    while time.time() - start < 5.0:
        if isinstance(app.screen, expected_screen_class):
            return
        await pilot.pause(0.1)
    raise AssertionError(
        f"Screen never changed to {expected_screen_class.__name__}. "
        f"Final screen: {app.screen.__class__.__name__}"
    )


# ── Scenario 1: client_secret_post (no CASetupScreen) ────────────────────────

@pytest.mark.asyncio
async def test_e2e_full_install_client_secret_post(tmp_path):
    """Navigate all screens with client_secret_post and verify generated configs."""
    with (
        patch("installer.screens.welcome._run_checks", return_value=_ALL_OK_CHECKS),
        patch("installer.runner.init_db",     return_value=(True, "")),
        patch("installer.runner.init_keys",   return_value=(True, "")),
        patch("installer.runner.add_client",  return_value=(True, "")),
    ):
        app = InstallerApp(x2fa_home=tmp_path)
        async with app.run_test(size=_SIZE) as pilot:

            # ── MainMenu → WelcomeScreen ──────────────────────────────────
            await pilot.click("#install")
            await _wait_for_screen_change(pilot, app, "Welcome")

            # ── WelcomeScreen → DatabaseScreen ────────────────────────────
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Database")

            # ── DatabaseScreen → DomainScreen ─────────────────────────────
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Domain")

            # ── DomainScreen: type domain → SecurityScreen ────────────────
            app.screen.query_one("#domain", Input).value = "e2e.example.com"
            app.config.domain = "e2e.example.com"
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Security")

            # ── SecurityScreen: keys auto-generated on mount, continue ─────
            secret_key  = app.config.secret_key
            secret_salt = app.config.secret_salt
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Client")

            # ── ClientScreen: fill data, select client_secret_post ─────────
            app.screen.query_one("#client_id",    Input).value = "myapp.example.com"
            app.screen.query_one("#redirect_uri", Input).value = "https://myapp.example.com/cb"
            app.config.client_id = "myapp.example.com"
            app.config.client_redirect_uri = "https://myapp.example.com/cb"
            await pilot.click("#client_secret_post")
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Review")

            # ── ReviewScreen: confirm and proceed ─────────────────────────
            await pilot.click("#confirm")
            await _wait_for_screen_change(pilot, app, "Summary")

    # ── Verify generated config files ─────────────────────────────────────────
    x2fa = _read_toml(tmp_path, "x2fa_config.toml")
    assert x2fa["production"]["DOMAIN"]   == "e2e.example.com"
    assert x2fa["production"]["ORIGIN"]   == "https://e2e.example.com"
    assert x2fa["production"]["TESTING"]  is False

    security = _read_toml(tmp_path, "security_config.toml")
    assert security["production"]["SECRET_KEY"]             == secret_key
    assert security["production"]["SECRET_SALT"]            == secret_salt
    assert security["production"]["SESSION_COOKIE_SECURE"]  is True

    db = _read_toml(tmp_path, "db_config.toml")
    uri = db["production"]["SQLALCHEMY_DATABASE_URI"]
    assert uri.startswith("sqlite:///")
    assert "db.sqlite" in uri

    ratelimit = _read_toml(tmp_path, "ratelimit_config.toml")
    assert ratelimit["production"]["RATELIMIT_STORAGE_URI"] == "memory://"

    babel = _read_toml(tmp_path, "babel_config.toml")
    assert "BABEL_DEFAULT_LOCALE" in babel["default"]


# ── Scenario 2: tls_client_auth (goes through CASetupScreen) ─────────────────

@pytest.mark.asyncio
async def test_e2e_full_install_tls_client_auth(tmp_path):
    """Navigate all screens with tls_client_auth (through CASetupScreen) and verify configs."""
    with (
        patch("installer.screens.welcome._run_checks", return_value=_ALL_OK_CHECKS),
        patch("installer.runner.init_db",     return_value=(True, "")),
        patch("installer.runner.init_keys",   return_value=(True, "")),
        patch("installer.runner.add_ca",      return_value=(True, "")),
        patch("installer.runner.add_client",  return_value=(True, "")),
        patch("installer.ca.generate_ca"),
        patch("installer.ca.issue_client_cert",
              return_value={"cert": str(tmp_path / "client.pem"),
                            "key":  str(tmp_path / "client.key")}),
    ):
        app = InstallerApp(x2fa_home=tmp_path)
        async with app.run_test(size=_SIZE) as pilot:

            # ── MainMenu → WelcomeScreen ──────────────────────────────────
            await pilot.click("#install")
            await _wait_for_screen_change(pilot, app, "Welcome")

            # ── WelcomeScreen → DatabaseScreen ────────────────────────────
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Database")

            # ── DatabaseScreen → DomainScreen ─────────────────────────────
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Domain")

            # ── DomainScreen: type domain ─────────────────────────────────
            app.screen.query_one("#domain", Input).value = "tls.example.com"
            app.config.domain = "tls.example.com"
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Security")

            # ── SecurityScreen: keys auto-generated, continue ─────────────
            secret_key = app.config.secret_key
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Client")

            # ── ClientScreen: fill data, keep tls_client_auth default ──────
            app.screen.query_one("#client_id",    Input).value = "client.example.com"
            app.screen.query_one("#redirect_uri", Input).value = "https://client.example.com/cb"
            app.config.client_id = "client.example.com"
            app.config.client_redirect_uri = "https://client.example.com/cb"
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "CASetup")

            # ── CASetupScreen: set ca_name, set generate action ───────────
            # ca_action defaults to "" in config; set it explicitly so the
            # _validate() / execute.py generate-branch are triggered correctly.
            app.config.ca_action = "generate"
            app.screen.query_one("#ca_name", Input).value = "test-ca"
            app.config.ca_name = "test-ca"
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Review")

            # ── ReviewScreen: confirm and proceed ─────────────────────────
            await pilot.click("#confirm")
            await _wait_for_screen_change(pilot, app, "Summary")

    # ── Verify generated config files ─────────────────────────────────────────
    x2fa = _read_toml(tmp_path, "x2fa_config.toml")
    assert x2fa["production"]["DOMAIN"]  == "tls.example.com"
    assert x2fa["production"]["ORIGIN"]  == "https://tls.example.com"
    assert x2fa["production"]["TESTING"] is False

    security = _read_toml(tmp_path, "security_config.toml")
    assert security["production"]["SECRET_KEY"] == secret_key

    db = _read_toml(tmp_path, "db_config.toml")
    assert db["production"]["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")

    ratelimit = _read_toml(tmp_path, "ratelimit_config.toml")
    assert ratelimit["production"]["RATELIMIT_STRATEGY"] == "moving-window"


# ── Scenario 3: private_key_jwt + PostgreSQL ──────────────────────────────────

@pytest.mark.asyncio
async def test_e2e_full_install_private_key_jwt_postgres(tmp_path):
    """private_key_jwt: CA is generated and registered, but no client cert is issued.
    PostgreSQL URI flows through to db_config.toml."""
    pg_uri = "postgresql://x2fa:secret@db.example.com/x2fa"

    with (
        patch("installer.screens.welcome._run_checks", return_value=_ALL_OK_CHECKS),
        patch("installer.runner.init_db",    return_value=(True, "")),
        patch("installer.runner.init_keys",  return_value=(True, "")),
        patch("installer.runner.add_ca",     return_value=(True, "")),
        patch("installer.runner.add_client", return_value=(True, "")),
        patch("installer.ca.generate_ca"),
        # issue_client_cert must NOT be called for private_key_jwt
        patch("installer.ca.issue_client_cert",
              side_effect=AssertionError("issue_client_cert called for private_key_jwt")),
    ):
        app = InstallerApp(x2fa_home=tmp_path)
        async with app.run_test(size=_SIZE) as pilot:

            # ── MainMenu → WelcomeScreen ──────────────────────────────────
            await pilot.click("#install")
            await _wait_for_screen_change(pilot, app, "Welcome")

            # ── WelcomeScreen → DatabaseScreen ────────────────────────────
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Database")

            # ── DatabaseScreen: switch to PostgreSQL, enter URI ────────────
            await pilot.click("#postgres")
            app.screen.query_one("#db_uri", Input).value = pg_uri
            app.config.db_uri = pg_uri
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Domain")

            # ── DomainScreen ──────────────────────────────────────────────
            app.screen.query_one("#domain", Input).value = "jwt.example.com"
            app.config.domain = "jwt.example.com"
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Security")

            # ── SecurityScreen ────────────────────────────────────────────
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Client")

            # ── ClientScreen: select private_key_jwt, enter JWKS URI ──────
            app.screen.query_one("#client_id",    Input).value = "rp.example.com"
            app.screen.query_one("#redirect_uri", Input).value = "https://rp.example.com/cb"
            app.config.client_id = "rp.example.com"
            app.config.client_redirect_uri = "https://rp.example.com/cb"
            await pilot.click("#private_key_jwt")
            app.screen.query_one("#jwks_uri", Input).value = "https://rp.example.com/.well-known/jwks.json"
            app.config.client_jwks_uri = "https://rp.example.com/.well-known/jwks.json"
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "CASetup")

            # ── CASetupScreen: generate CA ────────────────────────────────
            app.config.ca_action = "generate"
            app.screen.query_one("#ca_name", Input).value = "jwt-ca"
            app.config.ca_name = "jwt-ca"
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Review")

            # ── ReviewScreen: confirm and proceed ─────────────────────────
            await pilot.click("#confirm")
            await _wait_for_screen_change(pilot, app, "Summary")

    # ── Verify generated config files ─────────────────────────────────────────
    x2fa = _read_toml(tmp_path, "x2fa_config.toml")
    assert x2fa["production"]["DOMAIN"] == "jwt.example.com"

    db = _read_toml(tmp_path, "db_config.toml")
    assert db["production"]["SQLALCHEMY_DATABASE_URI"] == pg_uri


# ── Scenario 4: tls_client_auth + CA import ───────────────────────────────────

@pytest.mark.asyncio
async def test_e2e_full_install_tls_ca_import(tmp_path):
    """tls_client_auth with an imported CA: generate_ca is NOT called, the
    import path is used as the CA cert for add_ca and issue_client_cert."""
    ca_import_path = "/existing/ca.pem"

    with (
        patch("installer.screens.welcome._run_checks", return_value=_ALL_OK_CHECKS),
        patch("installer.runner.init_db",    return_value=(True, "")),
        patch("installer.runner.init_keys",  return_value=(True, "")),
        patch("installer.runner.add_ca",     return_value=(True, "")),
        patch("installer.runner.add_client", return_value=(True, "")),
        # generate_ca must NOT be called in import mode
        patch("installer.ca.generate_ca",
              side_effect=AssertionError("generate_ca called in CA import mode")),
        patch("installer.ca.issue_client_cert",
              return_value={"cert": str(tmp_path / "client.pem"),
                            "key":  str(tmp_path / "client.key")}),
    ):
        app = InstallerApp(x2fa_home=tmp_path)
        async with app.run_test(size=_SIZE) as pilot:

            # ── MainMenu → WelcomeScreen ──────────────────────────────────
            await pilot.click("#install")
            await _wait_for_screen_change(pilot, app, "Welcome")

            # ── WelcomeScreen → DatabaseScreen ────────────────────────────
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Database")

            # ── DatabaseScreen → DomainScreen ─────────────────────────────
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Domain")

            # ── DomainScreen ──────────────────────────────────────────────
            app.screen.query_one("#domain", Input).value = "import.example.com"
            app.config.domain = "import.example.com"
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Security")

            # ── SecurityScreen ────────────────────────────────────────────
            secret_key = app.config.secret_key
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Client")

            # ── ClientScreen: tls_client_auth default ─────────────────────
            app.screen.query_one("#client_id",    Input).value = "app.example.com"
            app.screen.query_one("#redirect_uri", Input).value = "https://app.example.com/cb"
            app.config.client_id = "app.example.com"
            app.config.client_redirect_uri = "https://app.example.com/cb"
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "CASetup")

            # ── CASetupScreen: switch to import, enter paths ───────────────
            await pilot.click("#import")
            app.screen.query_one("#ca_name_imp",    Input).value = "existing-ca"
            app.screen.query_one("#ca_import_path", Input).value = ca_import_path
            app.config.ca_name = "existing-ca"
            app.config.ca_cert_path = ca_import_path
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Review")

            # ── ReviewScreen: confirm and proceed ─────────────────────────
            await pilot.click("#confirm")
            await _wait_for_screen_change(pilot, app, "Summary")

    # ── Verify generated config files ─────────────────────────────────────────
    x2fa = _read_toml(tmp_path, "x2fa_config.toml")
    assert x2fa["production"]["DOMAIN"] == "import.example.com"

    security = _read_toml(tmp_path, "security_config.toml")
    assert security["production"]["SECRET_KEY"] == secret_key

    db = _read_toml(tmp_path, "db_config.toml")
    assert db["production"]["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")


# ── Scenario 5: self_signed_tls_client_auth (no CASetupScreen) ───────────────

@pytest.mark.asyncio
async def test_e2e_full_install_self_signed_tls(tmp_path):
    """self_signed_tls_client_auth skips CASetupScreen; the cert path is passed
    to add_client; no CA infrastructure is set up."""
    ss_cert = str(tmp_path / "self_signed.pem")

    with (
        patch("installer.screens.welcome._run_checks", return_value=_ALL_OK_CHECKS),
        patch("installer.runner.init_db",    return_value=(True, "")),
        patch("installer.runner.init_keys",  return_value=(True, "")),
        patch("installer.runner.add_client", return_value=(True, "")),
        # Neither CA-related function must be called
        patch("installer.ca.generate_ca",
              side_effect=AssertionError("generate_ca should not be called")),
        patch("installer.ca.issue_client_cert",
              side_effect=AssertionError("issue_client_cert should not be called")),
    ):
        app = InstallerApp(x2fa_home=tmp_path)
        async with app.run_test(size=_SIZE) as pilot:

            # ── MainMenu → WelcomeScreen ──────────────────────────────────
            await pilot.click("#install")
            await _wait_for_screen_change(pilot, app, "Welcome")

            # ── WelcomeScreen → DatabaseScreen ────────────────────────────
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Database")

            # ── DatabaseScreen → DomainScreen ─────────────────────────────
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Domain")

            # ── DomainScreen ──────────────────────────────────────────────
            app.screen.query_one("#domain", Input).value = "ss.example.com"
            app.config.domain = "ss.example.com"
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Security")

            # ── SecurityScreen ────────────────────────────────────────────
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Client")

            # ── ClientScreen: select self_signed, enter cert path ─────────
            app.screen.query_one("#client_id",    Input).value = "pinned.example.com"
            app.screen.query_one("#redirect_uri", Input).value = "https://pinned.example.com/cb"
            app.config.client_id = "pinned.example.com"
            app.config.client_redirect_uri = "https://pinned.example.com/cb"
            await pilot.click("#self_signed_tls_client_auth")
            app.screen.query_one("#ss_cert_path", Input).value = ss_cert
            app.config.client_self_signed_cert_path = ss_cert
            await pilot.click("#next")
            # Must go to ReviewScreen (not CASetupScreen)
            await _wait_for_screen_change(pilot, app, "Review")

            # ── ReviewScreen: confirm and proceed ─────────────────────────
            await pilot.click("#confirm")
            await _wait_for_screen_change(pilot, app, "Summary")

    # ── Verify generated config files ─────────────────────────────────────────
    x2fa = _read_toml(tmp_path, "x2fa_config.toml")
    assert x2fa["production"]["DOMAIN"] == "ss.example.com"

    db = _read_toml(tmp_path, "db_config.toml")
    assert db["production"]["SQLALCHEMY_DATABASE_URI"].startswith("sqlite:///")


# ── Scenario 6: client_secret_jwt + Redis rate limiter ───────────────────────

@pytest.mark.asyncio
async def test_e2e_full_install_client_secret_jwt_redis(tmp_path):
    """client_secret_jwt with Redis rate limiter: ratelimit_config.toml must
    contain the Redis URI entered in the SecurityScreen."""
    redis_uri = "redis://redis.example.com:6379/2"

    with (
        patch("installer.screens.welcome._run_checks", return_value=_ALL_OK_CHECKS),
        patch("installer.runner.init_db",    return_value=(True, "")),
        patch("installer.runner.init_keys",  return_value=(True, "")),
        patch("installer.runner.add_client", return_value=(True, "")),
    ):
        app = InstallerApp(x2fa_home=tmp_path)
        async with app.run_test(size=_SIZE) as pilot:

            # ── MainMenu → WelcomeScreen ──────────────────────────────────
            await pilot.click("#install")
            await _wait_for_screen_change(pilot, app, "Welcome")

            # ── WelcomeScreen → DatabaseScreen ────────────────────────────
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Database")

            # ── DatabaseScreen → DomainScreen ─────────────────────────────
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Domain")

            # ── DomainScreen ──────────────────────────────────────────────
            app.screen.query_one("#domain", Input).value = "redis.example.com"
            app.config.domain = "redis.example.com"
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Security")

            # ── SecurityScreen: enable Redis, enter URI ───────────────────
            await pilot.click("#use_redis")
            app.screen.query_one("#redis_uri", Input).value = redis_uri
            app.config.ratelimit_storage_uri = redis_uri
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Client")

            # ── ClientScreen: select client_secret_jwt ────────────────────
            app.screen.query_one("#client_id",    Input).value = "app.example.com"
            app.screen.query_one("#redirect_uri", Input).value = "https://app.example.com/cb"
            app.config.client_id = "app.example.com"
            app.config.client_redirect_uri = "https://app.example.com/cb"
            await pilot.click("#client_secret_jwt")
            await pilot.click("#next")
            await _wait_for_screen_change(pilot, app, "Review")

            # ── ReviewScreen: confirm and proceed ─────────────────────────
            await pilot.click("#confirm")
            await _wait_for_screen_change(pilot, app, "Summary")

    # ── Verify generated config files ─────────────────────────────────────────
    ratelimit = _read_toml(tmp_path, "ratelimit_config.toml")
    assert ratelimit["production"]["RATELIMIT_STORAGE_URI"] == redis_uri
    assert ratelimit["production"]["RATELIMIT_STRATEGY"]    == "moving-window"

    x2fa = _read_toml(tmp_path, "x2fa_config.toml")
    assert x2fa["production"]["DOMAIN"] == "redis.example.com"
