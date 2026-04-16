from pathlib import Path

from textual.app import App, ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

from .models import InstallConfig

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
    height: 5; 
    align: right middle;
    margin-top: 2;
    border-top: solid $panel-lighten-2;
    padding-top: 1;
}

Button {
    margin-left: 1;
    width: auto;  
    height: 3;
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


class MainMenuScreen(Screen):
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

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="panel"):
            yield Static(
                "X2FA Installer\n[dim]FIDO2 Microservice – PKI Setup[/dim]",
                id="logo",
                markup=True,
            )
            yield Button("⚙   Fresh Installation",  id="install",   variant="primary")
            yield Button("🔑  Manage CAs",           id="manage_ca", variant="default")
            yield Button("✕   Quit",                 id="quit",      variant="error")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "install":
                from .screens.welcome import WelcomeScreen
                self.app.push_screen(WelcomeScreen())
            case "manage_ca":
                from .screens.ca_manage import CAManageScreen
                self.app.push_screen(CAManageScreen())
            case "quit":
                self.app.exit()


class InstallerApp(App[None]):
    TITLE = "X2FA Installer"
    CSS = APP_CSS

    def __init__(self) -> None:
        super().__init__()
        self.config = InstallConfig(install_root=Path.cwd())

    def on_mount(self) -> None:
        self.push_screen(MainMenuScreen())
