from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Collapsible, Footer, Header, Markdown, Static

from installer.models import InstallConfig

APP_CSS = """
Screen {
    align: center top;
}

#panel {
    width: 82;
    max-width: 100%;
    border: round $accent;
    padding: 1 3;
    margin: 1 0;
    height: auto;
}

.screen-title {
    text-style: bold;
    color: $accent;
    text-align: center;
    padding-bottom: 1;
    width: 100%;
    border-bottom: solid $panel-lighten-2;
    margin-bottom: 1;
}

.field-label {
    color: $text-muted;
    margin-top: 1;
}

.hint {
    color: $text-disabled;
    margin-top: 0;
}

.section-sep {
    margin-top: 1;
    border-top: dashed $panel-lighten-1;
}

#buttons {
    layout: horizontal;
    height: auto;
    align: right middle;
    margin-top: 2;
    border-top: solid $panel-lighten-2;
    padding-top: 1;
}

Button {
    margin-left: 1;
    width: auto;
}

.hidden {
    display: none;
}

Log {
    height: 14;
    border: solid $panel-lighten-2;
    margin-top: 1;
    background: $surface-darken-1;
}

RadioSet {
    border: none;
    height: auto;
    padding: 0;
    margin: 0 0 0 2;
}

Input {
    margin-top: 0;
}

Checkbox {
    margin-top: 1;
}
"""


_MAIN_HELP_TEXT = """\
## X2FA Installer

This installer walks through every configuration step and sets up X2FA automatically.

### Fresh Installation

Runs the full setup wizard:

1. **Preflight checks** — Python ≥ 3.11, uv, port 5000, Redis
2. **Database** — SQLite (default), PostgreSQL, or MySQL
3. **Domain & Proxy** — public hostname and reverse proxy type
4. **Security** — auto-generates `SECRET_KEY` and `SECRET_SALT`; optional Redis URI
5. **First OIDC Client** — client ID, redirect URI, authentication method
6. **Certificate Authority** *(PKI methods only)* — generate or import a CA
7. **Review** — read-only summary before anything is written
8. **Execute** — writes config files, initialises the database, registers the CA and client
9. **Summary** — start command, generated files, reverse proxy snippet, next-steps checklist

Config files are written to `~/.config/x2fa/`.
Data files (CA key, database) are written to `~/.local/share/x2fa/`.

Use `--config-root <dir>` to relocate everything under a different base directory.

### Manage CAs

Add, list, revoke, or renew Certificate Authorities without re-running the full installer.
Use this when a CA is expiring or when you want to add a second CA for a new client.

### F1 Help

Every screen has a contextual help panel. Press `F1` (or click the panel title) to
expand it. The panel explains every field, the available options, and recommended values.
"""


class MainMenuScreen(Screen):
    BINDINGS = [("f1", "toggle_help", "Help")]

    CSS = """
    #logo {
        text-align: center;
        color: $accent;
        padding: 2 0;
        width: 100%;
    }
    #panel Button {
        width: 100%;
        margin-bottom: 1;
        margin-top: 0;
    }
    """

    def action_toggle_help(self) -> None:
        self.query_one("#help_panel", Collapsible).collapsed ^= True

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="panel"):
            yield Static(
                "X2FA Installer\n[dim]FIDO2 Microservice – PKI Setup[/dim]",
                id="logo",
                markup=True,
            )
            with Collapsible(title="Help  (F1)", id="help_panel", collapsed=True):
                yield Markdown(_MAIN_HELP_TEXT)
            yield Button("⚙   Fresh Installation",  id="install",   variant="primary")
            yield Button("🔑  Manage CAs",           id="manage_ca", variant="default")
            yield Button("✕   Quit",                 id="quit",      variant="error")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "install":
                from installer.screens.welcome import WelcomeScreen
                self.app.push_screen(WelcomeScreen())
            case "manage_ca":
                from installer.screens.ca_manage import CAManageScreen
                self.app.push_screen(CAManageScreen())
            case "quit":
                self.app.exit()


class InstallerApp(App[None]):
    TITLE = "X2FA Installer"
    CSS = APP_CSS

    def __init__(self, config_root: Path | None = None) -> None:
        super().__init__()
        self.config = InstallConfig.load_session(
            install_root=Path.cwd(),
            config_root=config_root,
        )

    def push_screen(self, screen, *args, **kwargs):
        self.config.save_session()
        return super().push_screen(screen, *args, **kwargs)

    def pop_screen(self):
        self.config.save_session()
        return super().pop_screen()

    async def action_quit(self) -> None:
        self.config.save_session()
        await super().action_quit()

    def on_mount(self) -> None:
        self.push_screen(MainMenuScreen())
