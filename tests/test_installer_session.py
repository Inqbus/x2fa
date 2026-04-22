"""Tests for installer session persistence."""

from pathlib import Path
from unittest.mock import patch

import pytest
from textual.widgets import Input

from installer.app import InstallerApp
from installer.models import InstallConfig

_SIZE = (120, 60)

_ALL_OK_CHECKS = [
    {"label": "Running as x2fa",    "ok": True, "blocking": False},
    {"label": "Python ≥ 3.11",      "ok": True, "blocking": True},
    {"label": "uv package manager", "ok": True, "blocking": True},
    {"label": "Port 5000 free",     "ok": True, "blocking": False},
    {"label": "Redis reachable",    "ok": True, "blocking": False},
]


# ── Model-level unit tests (no TUI) ──────────────────────────────────────────

def test_save_and_load_roundtrip(tmp_path):
    """save_session / load_session round-trip preserves all user-entered fields."""
    cfg = InstallConfig(install_root=tmp_path, x2fa_home=tmp_path)
    cfg.domain = "roundtrip.example.com"
    cfg.proxy_type = "nginx"
    cfg.db_type = "postgres"
    cfg.db_uri = "postgresql://x2fa:pw@localhost/x2fa"
    cfg.client_id = "myapp"
    cfg.client_redirect_uri = "https://myapp.example.com/cb"
    cfg.save_session()

    cfg2 = InstallConfig.load_session(install_root=tmp_path, x2fa_home=tmp_path)
    assert cfg2.domain == "roundtrip.example.com"
    assert cfg2.proxy_type == "nginx"
    assert cfg2.db_type == "postgres"
    assert cfg2.db_uri == "postgresql://x2fa:pw@localhost/x2fa"
    assert cfg2.client_id == "myapp"
    assert cfg2.client_redirect_uri == "https://myapp.example.com/cb"


def test_load_session_missing_file_returns_fresh(tmp_path):
    """load_session returns a fresh config when no session file exists."""
    cfg = InstallConfig.load_session(install_root=tmp_path, x2fa_home=tmp_path)
    assert cfg.domain == ""
    assert cfg.db_type == "sqlite"


def test_load_session_corrupt_file_returns_fresh(tmp_path):
    """load_session returns a fresh config when the file is corrupt JSON."""
    sf = InstallConfig.session_file(tmp_path)
    sf.parent.mkdir(parents=True, exist_ok=True)
    sf.write_text("not valid json{{{")
    cfg = InstallConfig.load_session(install_root=tmp_path, x2fa_home=tmp_path)
    assert cfg.domain == ""


# ── TUI integration tests ─────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_session_saved_when_navigating_forward(tmp_path):
    """Values entered on a screen are persisted when the user navigates forward."""
    with patch("installer.screens.welcome._run_checks", return_value=_ALL_OK_CHECKS):
        app = InstallerApp(x2fa_home=tmp_path)
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#install")       # → WelcomeScreen
            await pilot.pause()
            await pilot.click("#next")          # → DatabaseScreen
            await pilot.pause()
            await pilot.click("#next")          # → DomainScreen
            await pilot.pause()

            # Type domain while on DomainScreen
            app.screen.query_one("#domain", Input).value = "forward.example.com"
            await pilot.pause()

            # Navigate away — this is the trigger that must save
            await pilot.click("#next")          # → SecurityScreen
            await pilot.pause()

    session = InstallConfig.load_session(install_root=tmp_path, x2fa_home=tmp_path)
    assert session.domain == "forward.example.com", (
        f"Expected 'forward.example.com', got '{session.domain}'"
    )


@pytest.mark.asyncio
async def test_session_saved_on_ctrl_q(tmp_path):
    """Values typed on the current screen are persisted when the user presses CTRL-Q."""
    with patch("installer.screens.welcome._run_checks", return_value=_ALL_OK_CHECKS):
        app = InstallerApp(x2fa_home=tmp_path)
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#install")       # → WelcomeScreen
            await pilot.pause()
            await pilot.click("#next")          # → DatabaseScreen
            await pilot.pause()
            await pilot.click("#next")          # → DomainScreen
            await pilot.pause()

            # Type domain but do NOT navigate — simulate user quitting mid-screen
            app.screen.query_one("#domain", Input).value = "ctrlq.example.com"
            await pilot.pause()
            await pilot.press("ctrl+q")
            await pilot.pause()

    session = InstallConfig.load_session(install_root=tmp_path, x2fa_home=tmp_path)
    assert session.domain == "ctrlq.example.com", (
        f"Expected 'ctrlq.example.com', got '{session.domain}'"
    )


@pytest.mark.asyncio
async def test_session_restored_on_restart(tmp_path):
    """A restarted InstallerApp pre-fills config from the saved session."""
    # ── First run: navigate to DomainScreen, enter domain, navigate forward ──
    with patch("installer.screens.welcome._run_checks", return_value=_ALL_OK_CHECKS):
        app = InstallerApp(x2fa_home=tmp_path)
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#install")
            await pilot.pause()
            await pilot.click("#next")
            await pilot.pause()
            await pilot.click("#next")          # → DomainScreen
            await pilot.pause()

            app.screen.query_one("#domain", Input).value = "restart.example.com"
            await pilot.pause()
            await pilot.click("#next")          # → SecurityScreen (saves)
            await pilot.pause()

    # ── Second run: config must be pre-loaded from session ─────────────────

    app2 = InstallerApp(x2fa_home=tmp_path)
    assert app2.config.domain == "restart.example.com", (
        f"Expected 'restart.example.com', got '{app2.config.domain}'"
    )
