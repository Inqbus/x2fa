"""End-to-end tests for the installer TUI application."""

from pathlib import Path

import pytest
from textual.widgets import Button, RadioSet

from installer.app import InstallerApp
from installer.models import InstallConfig


class InstallerAppTest(InstallerApp):
    """Test subclass that redirects all file I/O under tmp_path.

    Passes config_root=tmp_path so that XDG config and data paths resolve
    inside the pytest temporary directory — no Path.home() mocking needed.
    """

    def __init__(self, tmp_path: Path, **kwargs):
        super().__init__(config_root=tmp_path, **kwargs)
        self.config.install_root = tmp_path
        self.config.db_uri = ""
        self.config.domain = "test.example.com"
        self.config.client_id = "test-client"
        self.config.client_redirect_uri = "https://test.example.com/callback"


@pytest.mark.asyncio
async def test_installer_launches_main_menu(tmp_path):
    """Installer starts with main menu screen."""
    app = InstallerAppTest(tmp_path)

    async with app.run_test() as pilot:
        screen = app.screen
        assert screen is not None
        assert "MainMenuScreen" in screen.__class__.__name__

        buttons = screen.query(Button)
        button_ids = [b.id for b in buttons]
        assert "install" in button_ids
        assert "manage_ca" in button_ids
        assert "quit" in button_ids


@pytest.mark.asyncio
async def test_installer_database_screen(tmp_path):
    """Database screen shows database type options."""
    app = InstallerAppTest(tmp_path)

    async with app.run_test() as pilot:
        await pilot.click("#install")
        await pilot.pause()
        await pilot.click("#next")
        await pilot.pause()

        screen = app.screen
        assert "DatabaseScreen" in screen.__class__.__name__

        radio_set = screen.query(RadioSet)
        assert len(radio_set) > 0

        buttons = screen.query(Button)
        button_ids = [b.id for b in buttons]
        assert "back" in button_ids
        assert "next" in button_ids


@pytest.mark.asyncio
async def test_installer_ca_manage_screen(tmp_path):
    """CA Manage screen is accessible from main menu."""
    app = InstallerAppTest(tmp_path)

    async with app.run_test() as pilot:
        await pilot.click("#manage_ca")
        await pilot.pause()

        screen = app.screen
        assert "CAManageScreen" in screen.__class__.__name__


@pytest.mark.asyncio
async def test_installer_config_preserved_on_back_navigation(tmp_path):
    """Config values set before navigation are retained when going back."""
    app = InstallerAppTest(tmp_path)

    async with app.run_test() as pilot:
        original_domain = app.config.domain

        await pilot.click("#install")
        await pilot.pause()
        await pilot.click("#next")
        await pilot.pause()
        await pilot.click("#back")
        await pilot.pause()

        assert app.config.domain == original_domain
