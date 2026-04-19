"""End-to-end tests for the installer TUI application."""

import tempfile
from pathlib import Path

import pytest
from textual.app import App
from textual.widgets import Button, Static, Input, RadioSet

from installer.app import InstallerApp
from installer.models import InstallConfig


class InstallerAppTest(InstallerApp):
    """Test subclass that uses a temporary install root."""
    
    def __init__(self, tmp_path: Path, **kwargs):
        super().__init__(**kwargs)
        self.config.install_root = tmp_path
        self.config.ca_key_path = str(tmp_path / "ca_key.pem")
        self.config.ca_cert_path = str(tmp_path / "ca_cert.pem")
        self.config.db_uri = ""
        self.config.domain = "test.example.com"
        self.config.client_id = "test-client"
        self.config.client_redirect_uri = "https://test.example.com/callback"


@pytest.mark.asyncio
async def test_installer_launches_main_menu():
    """Installer starts with main menu screen."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
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
async def test_installer_database_screen():
    """Database screen shows database type options."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
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
async def test_installer_ca_manage_screen():
    """CA Manage screen is accessible from main menu."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        app = InstallerAppTest(tmp_path)
        
        async with app.run_test() as pilot:
            await pilot.click("#manage_ca")
            await pilot.pause()
            
            screen = app.screen
            assert "CAManageScreen" in screen.__class__.__name__


@pytest.mark.asyncio
async def test_installer_config_cleared_on_reinstall():
    """Config is properly reset when navigating back through screens."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
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
