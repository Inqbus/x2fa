"""Tests for installer TUI screens — rendering, validation, and navigation."""

from pathlib import Path
from unittest.mock import patch

import pytest
from textual.app import App
from textual.widgets import Button, Input

from installer.app import APP_CSS
from installer.models import InstallConfig

# Screens contain many fields; the default 80×24 test terminal clips the
# #next button below the visible region, causing OutOfBounds on click.
_SIZE = (120, 60)


class DirectScreenApp(App[None]):
    """Test helper: starts directly on the given screen.

    Inherits from App[None] rather than InstallerApp to avoid Textual's
    all-handler dispatch calling InstallerApp.on_mount (which would push
    MainMenuScreen on top of our test screen).

    config_root=tmp_path redirects all XDG file writes into the pytest
    temporary directory — no mocking of Path.home() required.
    """

    TITLE = "X2FA Installer Test"
    CSS = APP_CSS

    def __init__(self, screen_cls, tmp_path: Path, config_overrides: dict | None = None):
        super().__init__()
        self.config = InstallConfig(install_root=tmp_path, config_root=tmp_path)
        self.config.domain = "test.example.com"
        self.config.client_id = "test-client"
        self.config.client_redirect_uri = "https://test.example.com/cb"
        if config_overrides:
            for k, v in config_overrides.items():
                setattr(self.config, k, v)
        self._screen_cls = screen_cls

    def on_mount(self) -> None:
        self.push_screen(self._screen_cls())


# ── WelcomeScreen ─────────────────────────────────────────────────────────────

class TestWelcomeScreen:
    @pytest.mark.asyncio
    async def test_quit_button_always_present(self, tmp_path):
        from installer.screens.welcome import WelcomeScreen
        app = DirectScreenApp(WelcomeScreen, tmp_path)
        async with app.run_test(size=_SIZE):
            assert "quit" in {b.id for b in app.screen.query(Button)}

    @pytest.mark.asyncio
    async def test_continue_shown_when_all_checks_pass(self, tmp_path):
        from installer.screens.welcome import WelcomeScreen
        passing = [{"label": "ok", "ok": True, "blocking": True}]
        app = DirectScreenApp(WelcomeScreen, tmp_path)
        with patch("installer.screens.welcome._run_checks", return_value=passing):
            async with app.run_test(size=_SIZE):
                assert "next" in {b.id for b in app.screen.query(Button)}

    @pytest.mark.asyncio
    async def test_continue_hidden_when_blocking_check_fails(self, tmp_path):
        from installer.screens.welcome import WelcomeScreen
        failing = [{"label": "uv missing", "ok": False, "blocking": True}]
        app = DirectScreenApp(WelcomeScreen, tmp_path)
        with patch("installer.screens.welcome._run_checks", return_value=failing):
            async with app.run_test(size=_SIZE):
                assert "next" not in {b.id for b in app.screen.query(Button)}

    @pytest.mark.asyncio
    async def test_continue_navigates_to_database_screen(self, tmp_path):
        from installer.screens.welcome import WelcomeScreen
        passing = [{"label": "ok", "ok": True, "blocking": False}]
        app = DirectScreenApp(WelcomeScreen, tmp_path)
        with patch("installer.screens.welcome._run_checks", return_value=passing):
            async with app.run_test(size=_SIZE) as pilot:
                await pilot.click("#next")
                await pilot.pause()
                assert "DatabaseScreen" in app.screen.__class__.__name__

    @pytest.mark.asyncio
    async def test_non_blocking_failures_still_show_continue(self, tmp_path):
        from installer.screens.welcome import WelcomeScreen
        mixed = [
            {"label": "Python ok",  "ok": True,  "blocking": True},
            {"label": "Redis down", "ok": False, "blocking": False,
             "hint": "optional"},
        ]
        app = DirectScreenApp(WelcomeScreen, tmp_path)
        with patch("installer.screens.welcome._run_checks", return_value=mixed):
            async with app.run_test(size=_SIZE):
                assert "next" in {b.id for b in app.screen.query(Button)}


# ── DatabaseScreen ────────────────────────────────────────────────────────────

class TestDatabaseScreen:
    @pytest.mark.asyncio
    async def test_sqlite_selected_by_default(self, tmp_path):
        from installer.screens.database import DatabaseScreen
        app = DirectScreenApp(DatabaseScreen, tmp_path)
        async with app.run_test(size=_SIZE):
            assert app.config.db_type == "sqlite"

    @pytest.mark.asyncio
    async def test_uri_input_hidden_for_sqlite(self, tmp_path):
        from installer.screens.database import DatabaseScreen
        app = DirectScreenApp(DatabaseScreen, tmp_path)
        async with app.run_test(size=_SIZE):
            uri = app.screen.query_one("#db_uri", Input)
            assert "hidden" in uri.classes

    @pytest.mark.asyncio
    async def test_continue_navigates_to_domain_screen(self, tmp_path):
        from installer.screens.database import DatabaseScreen
        app = DirectScreenApp(DatabaseScreen, tmp_path)
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "DomainScreen" in app.screen.__class__.__name__

    @pytest.mark.asyncio
    async def test_validation_blocks_postgres_without_uri(self, tmp_path):
        from installer.screens.database import DatabaseScreen
        app = DirectScreenApp(DatabaseScreen, tmp_path,
                              config_overrides={"db_type": "postgres", "db_uri": ""})
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "DatabaseScreen" in app.screen.__class__.__name__

    @pytest.mark.asyncio
    async def test_validation_blocks_mysql_without_uri(self, tmp_path):
        from installer.screens.database import DatabaseScreen
        app = DirectScreenApp(DatabaseScreen, tmp_path,
                              config_overrides={"db_type": "mysql", "db_uri": ""})
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "DatabaseScreen" in app.screen.__class__.__name__

    @pytest.mark.asyncio
    async def test_postgres_with_uri_navigates_to_domain(self, tmp_path):
        from installer.screens.database import DatabaseScreen
        app = DirectScreenApp(DatabaseScreen, tmp_path, config_overrides={
            "db_type": "postgres",
            "db_uri": "postgresql://u:p@localhost/x2fa",
        })
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "DomainScreen" in app.screen.__class__.__name__


# ── DomainScreen ──────────────────────────────────────────────────────────────

class TestDomainScreen:
    @pytest.mark.asyncio
    async def test_continue_navigates_to_security_screen(self, tmp_path):
        from installer.screens.domain import DomainScreen
        app = DirectScreenApp(DomainScreen, tmp_path)
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "SecurityScreen" in app.screen.__class__.__name__

    @pytest.mark.asyncio
    async def test_validation_blocks_empty_domain(self, tmp_path):
        from installer.screens.domain import DomainScreen
        app = DirectScreenApp(DomainScreen, tmp_path, config_overrides={"domain": ""})
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "DomainScreen" in app.screen.__class__.__name__


# ── SecurityScreen ────────────────────────────────────────────────────────────

class TestSecurityScreen:
    @pytest.mark.asyncio
    async def test_keys_auto_generated_on_mount(self, tmp_path):
        from installer.screens.security import SecurityScreen
        app = DirectScreenApp(SecurityScreen, tmp_path)
        async with app.run_test(size=_SIZE):
            assert len(app.config.secret_key) == 64
            assert len(app.config.secret_salt) == 32

    @pytest.mark.asyncio
    async def test_keys_are_hex_strings(self, tmp_path):
        from installer.screens.security import SecurityScreen
        app = DirectScreenApp(SecurityScreen, tmp_path)
        async with app.run_test(size=_SIZE):
            int(app.config.secret_key, 16)
            int(app.config.secret_salt, 16)

    @pytest.mark.asyncio
    async def test_regen_changes_secret_key(self, tmp_path):
        from installer.screens.security import SecurityScreen
        app = DirectScreenApp(SecurityScreen, tmp_path)
        async with app.run_test(size=_SIZE) as pilot:
            original = app.config.secret_key
            await pilot.click("#regen")
            await pilot.pause()
            assert app.config.secret_key != original

    @pytest.mark.asyncio
    async def test_continue_navigates_to_client_screen(self, tmp_path):
        from installer.screens.security import SecurityScreen
        app = DirectScreenApp(SecurityScreen, tmp_path)
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "ClientScreen" in app.screen.__class__.__name__

    @pytest.mark.asyncio
    async def test_validation_blocks_empty_secret_key(self, tmp_path):
        from installer.screens.security import SecurityScreen
        app = DirectScreenApp(SecurityScreen, tmp_path,
                              config_overrides={"secret_key": "", "secret_salt": "x" * 32})
        async with app.run_test(size=_SIZE) as pilot:
            # Clear the auto-generated key from on_mount before clicking
            app.config.secret_key = ""
            app.screen.query_one("#secret_key", Input).value = ""
            await pilot.click("#next")
            await pilot.pause()
            assert "SecurityScreen" in app.screen.__class__.__name__


# ── ClientScreen ──────────────────────────────────────────────────────────────

class TestClientScreen:
    @pytest.mark.asyncio
    async def test_tls_client_auth_is_default(self, tmp_path):
        from installer.screens.client import ClientScreen
        app = DirectScreenApp(ClientScreen, tmp_path)
        async with app.run_test(size=_SIZE):
            assert app.config.client_auth_method == "tls_client_auth"

    @pytest.mark.asyncio
    async def test_cert_dir_field_visible_for_tls(self, tmp_path):
        from installer.screens.client import ClientScreen
        app = DirectScreenApp(ClientScreen, tmp_path)
        async with app.run_test(size=_SIZE):
            assert "hidden" not in app.screen.query_one("#cert_out_dir", Input).classes

    @pytest.mark.asyncio
    async def test_jwks_uri_hidden_for_tls(self, tmp_path):
        from installer.screens.client import ClientScreen
        app = DirectScreenApp(ClientScreen, tmp_path)
        async with app.run_test(size=_SIZE):
            assert "hidden" in app.screen.query_one("#jwks_uri", Input).classes

    @pytest.mark.asyncio
    async def test_ss_cert_path_hidden_for_tls(self, tmp_path):
        from installer.screens.client import ClientScreen
        app = DirectScreenApp(ClientScreen, tmp_path)
        async with app.run_test(size=_SIZE):
            assert "hidden" in app.screen.query_one("#ss_cert_path", Input).classes

    @pytest.mark.asyncio
    async def test_validation_requires_client_id(self, tmp_path):
        from installer.screens.client import ClientScreen
        app = DirectScreenApp(ClientScreen, tmp_path, config_overrides={"client_id": ""})
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "ClientScreen" in app.screen.__class__.__name__

    @pytest.mark.asyncio
    async def test_validation_requires_redirect_uri(self, tmp_path):
        from installer.screens.client import ClientScreen
        app = DirectScreenApp(ClientScreen, tmp_path,
                              config_overrides={"client_redirect_uri": ""})
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "ClientScreen" in app.screen.__class__.__name__

    @pytest.mark.asyncio
    async def test_validation_requires_jwks_uri_for_private_key_jwt(self, tmp_path):
        from installer.screens.client import ClientScreen
        app = DirectScreenApp(ClientScreen, tmp_path, config_overrides={
            "client_auth_method": "private_key_jwt",
            "client_jwks_uri": "",
        })
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "ClientScreen" in app.screen.__class__.__name__

    @pytest.mark.asyncio
    async def test_validation_requires_cert_for_self_signed(self, tmp_path):
        from installer.screens.client import ClientScreen
        app = DirectScreenApp(ClientScreen, tmp_path, config_overrides={
            "client_auth_method": "self_signed_tls_client_auth",
            "client_self_signed_cert_path": "",
        })
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "ClientScreen" in app.screen.__class__.__name__

    @pytest.mark.asyncio
    async def test_pki_method_navigates_to_ca_setup(self, tmp_path):
        from installer.screens.client import ClientScreen
        app = DirectScreenApp(ClientScreen, tmp_path,
                              config_overrides={"client_auth_method": "tls_client_auth"})
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "CASetupScreen" in app.screen.__class__.__name__

    @pytest.mark.asyncio
    async def test_private_key_jwt_navigates_to_ca_setup(self, tmp_path):
        from installer.screens.client import ClientScreen
        app = DirectScreenApp(ClientScreen, tmp_path, config_overrides={
            "client_auth_method": "private_key_jwt",
            "client_jwks_uri": "https://app.example.com/.well-known/jwks.json",
        })
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "CASetupScreen" in app.screen.__class__.__name__

    @pytest.mark.asyncio
    async def test_secret_method_navigates_to_review(self, tmp_path):
        from installer.screens.client import ClientScreen
        app = DirectScreenApp(ClientScreen, tmp_path,
                              config_overrides={"client_auth_method": "client_secret_post"})
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "ReviewScreen" in app.screen.__class__.__name__


# ── CASetupScreen ─────────────────────────────────────────────────────────────

class TestCASetupScreen:
    @pytest.mark.asyncio
    async def test_generate_action_is_default(self, tmp_path):
        from installer.screens.ca_setup import CASetupScreen
        app = DirectScreenApp(CASetupScreen, tmp_path)
        async with app.run_test(size=_SIZE):
            assert app.config.ca_action == "generate"

    @pytest.mark.asyncio
    async def test_gen_fields_visible_import_fields_hidden_by_default(self, tmp_path):
        from installer.screens.ca_setup import CASetupScreen
        app = DirectScreenApp(CASetupScreen, tmp_path)
        async with app.run_test(size=_SIZE):
            gen = app.screen.query_one("#gen_fields")
            imp = app.screen.query_one("#imp_fields")
            assert "hidden" not in gen.classes
            assert "hidden" in imp.classes

    @pytest.mark.asyncio
    async def test_validation_requires_key_and_cert_for_generate(self, tmp_path):
        from installer.screens.ca_setup import CASetupScreen
        app = DirectScreenApp(CASetupScreen, tmp_path, config_overrides={
            "ca_action": "generate",
            "ca_key_path": "",
            "ca_cert_path": "",
        })
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "CASetupScreen" in app.screen.__class__.__name__

    @pytest.mark.asyncio
    async def test_validation_requires_import_path_for_import(self, tmp_path):
        from installer.screens.ca_setup import CASetupScreen
        app = DirectScreenApp(CASetupScreen, tmp_path, config_overrides={
            "ca_action": "import",
            "ca_import_path": "",
        })
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "CASetupScreen" in app.screen.__class__.__name__

    @pytest.mark.asyncio
    async def test_continue_with_valid_generate_navigates_to_review(self, tmp_path):
        from installer.screens.ca_setup import CASetupScreen
        app = DirectScreenApp(CASetupScreen, tmp_path, config_overrides={
            "ca_action": "generate",
            "ca_key_path": str(tmp_path / "ca_key.pem"),
            "ca_cert_path": str(tmp_path / "ca_cert.pem"),
        })
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "ReviewScreen" in app.screen.__class__.__name__

    @pytest.mark.asyncio
    async def test_continue_with_valid_import_navigates_to_review(self, tmp_path):
        from installer.screens.ca_setup import CASetupScreen
        app = DirectScreenApp(CASetupScreen, tmp_path, config_overrides={
            "ca_action": "import",
            "ca_import_path": "/existing/ca.pem",
        })
        async with app.run_test(size=_SIZE) as pilot:
            await pilot.click("#next")
            await pilot.pause()
            assert "ReviewScreen" in app.screen.__class__.__name__
