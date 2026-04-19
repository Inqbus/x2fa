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
    {"label": "Running as user",           "ok": True, "blocking": False},
    {"label": "Python ≥ 3.11",             "ok": True, "blocking": True},
    {"label": "uv package manager",        "ok": True, "blocking": True},
    {"label": "Port 5000 free",            "ok": True, "blocking": False},
    {"label": "Redis reachable",           "ok": True, "blocking": False},
]


def _read_toml(tmp_path: Path, filename: str) -> dict:
    return tomllib.loads((tmp_path / ".config" / "x2fa" / filename).read_text())


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
        app = InstallerApp(config_root=tmp_path)
        async with app.run_test(size=_SIZE) as pilot:

            # ── MainMenu → WelcomeScreen ──────────────────────────────────
            await pilot.click("#install")
            await pilot.pause()
            assert "WelcomeScreen" in app.screen.__class__.__name__

            # ── WelcomeScreen → DatabaseScreen ────────────────────────────
            await pilot.click("#next")
            await pilot.pause()
            assert "DatabaseScreen" in app.screen.__class__.__name__

            # ── DatabaseScreen: keep SQLite default → DomainScreen ────────
            await pilot.click("#next")
            await pilot.pause()
            assert "DomainScreen" in app.screen.__class__.__name__

            # ── DomainScreen: type domain → SecurityScreen ────────────────
            app.screen.query_one("#domain", Input).value = "e2e.example.com"
            await pilot.pause()
            await pilot.click("#next")
            await pilot.pause()
            assert "SecurityScreen" in app.screen.__class__.__name__

            # ── SecurityScreen: keys auto-generated on mount, continue ─────
            secret_key  = app.config.secret_key
            secret_salt = app.config.secret_salt
            await pilot.click("#next")
            await pilot.pause()
            assert "ClientScreen" in app.screen.__class__.__name__

            # ── ClientScreen: fill data, select client_secret_post ─────────
            app.screen.query_one("#client_id",    Input).value = "myapp.example.com"
            await pilot.pause()
            app.screen.query_one("#redirect_uri", Input).value = "https://myapp.example.com/cb"
            await pilot.pause()
            await pilot.click("#client_secret_post")
            await pilot.pause()
            await pilot.click("#next")
            await pilot.pause()

            # ── ExecuteScreen: poll until background worker completes ──────
            for _ in range(100):
                await pilot.pause(0.1)
                if "SummaryScreen" in app.screen.__class__.__name__:
                    break
            assert "SummaryScreen" in app.screen.__class__.__name__, \
                "Installation worker did not reach SummaryScreen in time"

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
        app = InstallerApp(config_root=tmp_path)
        async with app.run_test(size=_SIZE) as pilot:

            # ── MainMenu → WelcomeScreen ──────────────────────────────────
            await pilot.click("#install")
            await pilot.pause()

            # ── WelcomeScreen → DatabaseScreen ────────────────────────────
            await pilot.click("#next")
            await pilot.pause()

            # ── DatabaseScreen → DomainScreen ─────────────────────────────
            await pilot.click("#next")
            await pilot.pause()

            # ── DomainScreen: type domain ─────────────────────────────────
            app.screen.query_one("#domain", Input).value = "tls.example.com"
            await pilot.pause()
            await pilot.click("#next")
            await pilot.pause()

            # ── SecurityScreen: keys auto-generated, continue ─────────────
            secret_key = app.config.secret_key
            await pilot.click("#next")
            await pilot.pause()
            assert "ClientScreen" in app.screen.__class__.__name__

            # ── ClientScreen: fill data, keep tls_client_auth default ──────
            app.screen.query_one("#client_id",    Input).value = "client.example.com"
            await pilot.pause()
            app.screen.query_one("#redirect_uri", Input).value = "https://client.example.com/cb"
            await pilot.pause()
            await pilot.click("#next")
            await pilot.pause()
            assert "CASetupScreen" in app.screen.__class__.__name__

            # ── CASetupScreen: set ca_name, set generate action ───────────
            # ca_action defaults to "" in config; set it explicitly so the
            # _validate() / execute.py generate-branch are triggered correctly.
            app.config.ca_action = "generate"
            app.screen.query_one("#ca_name", Input).value = "test-ca"
            await pilot.pause()
            await pilot.click("#next")
            await pilot.pause()

            # ── ExecuteScreen: poll until background worker completes ──────
            for _ in range(100):
                await pilot.pause(0.1)
                if "SummaryScreen" in app.screen.__class__.__name__:
                    break
            assert "SummaryScreen" in app.screen.__class__.__name__, \
                "Installation worker did not reach SummaryScreen in time"

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
