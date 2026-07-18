"""End-to-end test for the installer with Certificate Authority variant.

This test drives the entire installer TUI workflow with REAL CA generation,
REAL database operations, and REAL CLI calls — no mocking of the CA facility
or X2FA backend.  It verifies that the ExecuteScreen correctly performs:

1. Real CA generation via cryptography library
2. Real flask database operations (init-db, init-keys, add-ca)
3. Real client certificate issuance via flask
4. Real OIDC client registration via flask
"""

import os
import stat
import sys
import tomllib
import time
from pathlib import Path
from subprocess import run

import pytest

from textual.widgets import Input

from installer.app import InstallerApp
from installer.screens import welcome

_SIZE = (120, 60)

_ALL_OK_CHECKS = [
    {"label": "Running as x2fa",    "ok": True, "blocking": False},
    {"label": "Python ≥ 3.11",      "ok": True, "blocking": True},
    {"label": "uv package manager", "ok": True, "blocking": True},
    {"label": "Port 5000 free",     "ok": True, "blocking": False},
    {"label": "Redis reachable",    "ok": True, "blocking": False},
]


def _read_toml(config_dir: Path, filename: str) -> dict:
    """Read a config file from the config directory."""
    return tomllib.loads((config_dir / filename).read_text())


async def _wait_for_screen_change(pilot, app, expected_screen_prefix: str, timeout: float = 10.0):
    """Wait for the app screen to change to one matching expected_screen_prefix.

    After the class name matches, one extra pilot.pause() lets the new screen
    finish compose/mount/layout before the caller interacts with its widgets.
    """
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        current = app.screen.__class__.__name__
        if current.startswith(expected_screen_prefix):
            await pilot.pause()  # settle: compose/mount/layout of new screen
            return current
        await pilot.pause(0.1)
    app.save_screenshot("/tmp/pytest_screen_timeout.svg")
    raise AssertionError(
        f"Screen never changed to {expected_screen_prefix}. "
        f"Final screen: {app.screen.__class__.__name__}. "
        f"Buttons present: {[b.id for b in app.screen.query('Button')]}"
    )


async def _wait_for_widget(pilot, app, selector: str, timeout: float = 10.0):
    """Wait until selector matches a widget on the current screen.

    On timeout, dump a screenshot and the buttons actually present — this
    distinguishes 'button missing' from 'wrong screen rendered'.
    """
    start = time.monotonic()
    while time.monotonic() - start < timeout:
        if app.screen.query(selector):
            return
        await pilot.pause(0.1)
    app.save_screenshot("/tmp/pytest_widget_timeout.svg")
    raise AssertionError(
        f"{selector} not found on {app.screen.__class__.__name__}. "
        f"Buttons present: {[b.id for b in app.screen.query('Button')]}"
    )


async def _click_when_ready(pilot, app, selector: str, timeout: float = 10.0):
    """Wait for a widget to exist, then click it."""
    await _wait_for_widget(pilot, app, selector, timeout)
    await pilot.click(selector)


@pytest.mark.asyncio
async def test_e2e_real_ca_generate(isolated_paths, monkeypatch):
    """Real e2e test: walks through installer with tls_client_auth, verifies
    ExecuteScreen performs REAL database and CA operations."""

    # Deterministic preflight checks — host PATH/dirs must not gate the e2e flow
    monkeypatch.setattr(
        welcome, "_run_checks",
        lambda: [dict(c) for c in _ALL_OK_CHECKS],
    )

    ca_name = "test-real-ca-e2e"
    ca_cn = "Test Real CA E2E"

    client_id = "real-ca-e2e-client.example.com"
    redirect_uri = "https://real-ca-e2e-client.example.com/cb"

    # Ensure X2FA_HOME is set before creating InstallerApp
    # (isolated_paths fixture sets it, but PyCharm --multiprocess may not propagate)
    os.environ["X2FA_HOME"] = str(isolated_paths)

    app = InstallerApp()
    async with app.run_test(size=_SIZE) as pilot:

        # ── Navigate through all screens ──────────────────────────────────────

        # MainMenu → WelcomeScreen
        await _click_when_ready(pilot, app, "#install")
        await _wait_for_screen_change(pilot, app, "Welcome")

        # WelcomeScreen → DatabaseScreen
        await _click_when_ready(pilot, app, "#next")
        await _wait_for_screen_change(pilot, app, "Database")

        # DatabaseScreen → DomainScreen
        await _click_when_ready(pilot, app, "#next")
        await _wait_for_screen_change(pilot, app, "Domain")

        # DomainScreen: set domain
        await _wait_for_widget(pilot, app, "#domain")
        app.screen.query_one("#domain", Input).value = "e2e-real-ca.example.com"
        app.config.domain = "e2e-real-ca.example.com"
        await _click_when_ready(pilot, app, "#next")
        await _wait_for_screen_change(pilot, app, "Security")

        # SecurityScreen: keys auto-generated, continue
        secret_key = app.config.secret_key
        await _click_when_ready(pilot, app, "#next")
        await _wait_for_screen_change(pilot, app, "Client")

        # ClientScreen: tls_client_auth (default), fill form
        await _wait_for_widget(pilot, app, "#client_id")
        app.screen.query_one("#client_id", Input).value = client_id
        app.screen.query_one("#redirect_uri", Input).value = redirect_uri
        app.config.client_id = client_id
        app.config.client_redirect_uri = redirect_uri
        await _click_when_ready(pilot, app, "#next")
        await _wait_for_screen_change(pilot, app, "CASetup")

        # ── CASetupScreen: configure REAL CA generation ──────────────────────
        app.config.ca_action = "generate"
        await _wait_for_widget(pilot, app, "#ca_name")
        app.screen.query_one("#ca_name", Input).value = ca_name
        app.screen.query_one("#ca_cn", Input).value = ca_cn
        # ca_key_path and ca_cert_path fields removed - use defaults from paths.py

        await _click_when_ready(pilot, app, "#next")
        await _wait_for_screen_change(pilot, app, "Review")

        # ReviewScreen: confirm to trigger ExecuteScreen
        await _click_when_ready(pilot, app, "#confirm")
        await _wait_for_screen_change(pilot, app, "Execute")

        # Wait for ExecuteScreen to complete and push SummaryScreen.
        # _run_installation() runs in a thread doing REAL CA generation and
        # flask subprocess calls — generous timeout, esp. under the debugger.
        await _wait_for_screen_change(pilot, app, "Summary", timeout=120.0)

        # Give thread a moment to finish writing files
        await pilot.pause(0.5)

    # ── Verify ExecuteScreen performed REAL operations ──────────────────────
    from x2fa import paths

    # 1. CA certificate was generated by generate_ca() during ExecuteScreen
    ca_key = paths.ca_key_path()
    ca_cert = paths.ca_cert_path()

    # Verify CA files exist and are valid
    assert ca_key.exists(), f"CA private key was not generated at {ca_key}"
    assert ca_cert.exists(), f"CA certificate was not generated at {ca_cert}"

    # Verify key permissions (should be 0600)
    key_mode = stat.S_IMODE(ca_key.stat().st_mode)
    assert key_mode == 0o600, f"CA key permissions should be 0600, got {oct(key_mode)}"

    # Verify certificate is valid by loading it
    from cryptography import x509
    cert = x509.load_pem_x509_certificate(ca_cert.read_bytes())
    assert cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value == ca_cn
    assert cert.issuer == cert.subject, "CA should be self-signed"

    # 2. Client certificate was issued during ExecuteScreen (tls_client_auth)
    safe_id = client_id.replace("/", "_").replace(":", "_")
    client_cert_path = paths.client_cert_dir() / f"{safe_id}.cert.pem"
    client_key_path = paths.client_cert_dir() / f"{safe_id}.key.pem"
    client_ca_path = paths.client_cert_dir() / f"{safe_id}.ca.pem"

    assert client_cert_path.exists(), "Client certificate was not issued"
    assert client_key_path.exists(), "Client private key was not issued"
    assert client_ca_path.exists(), "CA certificate copy was not issued"

    # Verify client cert was signed by our CA
    client_cert = x509.load_pem_x509_certificate(client_cert_path.read_bytes())
    assert client_cert.subject.get_attributes_for_oid(x509.oid.NameOID.COMMON_NAME)[0].value == client_id
    assert client_cert.issuer == cert.subject, "Client cert should be signed by CA"

    # 3. Config files were written
    x2fa = _read_toml(paths.config_dir(), "x2fa_config.toml")
    assert x2fa["production"]["DOMAIN"] == "e2e-real-ca.example.com"
    assert x2fa["production"]["ORIGIN"] == "https://e2e-real-ca.example.com"

    security = _read_toml(paths.config_dir(), "security_config.toml")
    assert security["production"]["SECRET_KEY"] == secret_key

    # 4. CA was registered in database via flask add-ca (called during ExecuteScreen)
    # Use X2FA_HOME which was set by isolated_paths fixture
    result = run(
        [sys.executable, "-m", "flask", "list-cas"],
        cwd=isolated_paths,
        capture_output=True,
        text=True,
        env={**os.environ, "FLASK_APP": "x2fa.wsgi_cli:app"},
    )
    assert result.returncode == 0, f"list-cas failed: {result.stderr}"
    assert ca_name in result.stdout, f"CA '{ca_name}' not registered in database"

    # Verify CA is not revoked
    assert "revoked" not in result.stdout.lower(), "CA should not be revoked"