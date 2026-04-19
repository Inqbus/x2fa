from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, RadioButton, RadioSet, Static


class DatabaseScreen(Screen):
    def compose(self) -> ComposeResult:
        cfg = self.app.config
        db = cfg.db_type or "sqlite"
        yield Header()
        with Container(id="panel"):
            yield Static("Database", classes="screen-title")
            yield Static("Backend:", classes="field-label")
            with RadioSet(id="db_type"):
                yield RadioButton(
                    "SQLite  (default, zero-config)", id="sqlite", value=db == "sqlite"
                )
                yield RadioButton("PostgreSQL", id="postgres", value=db == "postgres")
                yield RadioButton("MySQL / MariaDB", id="mysql", value=db == "mysql")

            default_db = str(cfg._data_dir() / "db.sqlite")
            db_hint = f"[dim]Database file: {default_db}[/]"
            yield Static(
                db_hint,
                id="sqlite_hint",
                markup=True,
                classes="hint" if db == "sqlite" else "hint hidden",
            )
            # URI input (shown for PG / MySQL)
            yield Static(
                "Connection URI:",
                id="uri_label",
                classes="field-label" if db != "sqlite" else "field-label hidden",
            )
            yield Input(
                value=cfg.db_uri,
                placeholder="postgresql://x2fa:pass@localhost/x2fa",
                id="db_uri",
                classes="" if db != "sqlite" else "hidden",
            )

            with Container(id="buttons"):
                yield Button("← Back", id="back")
                yield Button("Continue →", id="next", variant="primary")
        yield Footer()

    # ── Events ────────────────────────────────────────────────────────────

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id != "db_type":
            return
        selected = event.pressed.id  # "sqlite" | "postgres" | "mysql"
        self.app.config.db_type = selected
        sqlite = selected == "sqlite"

        self.query_one("#sqlite_hint").set_class(not sqlite, "hidden")
        self.query_one("#uri_label").set_class(sqlite, "hidden")
        uri = self.query_one("#db_uri", Input)
        uri.set_class(sqlite, "hidden")
        if not sqlite and not uri.value:
            uri.placeholder = (
                "postgresql://x2fa:pass@localhost/x2fa"
                if selected == "postgres"
                else "mysql+pymysql://x2fa:pass@localhost/x2fa"
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "db_uri":
            self.app.config.db_uri = event.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "back":
                self.app.pop_screen()
            case "next":
                cfg = self.app.config
                if cfg.db_type != "sqlite" and not cfg.db_uri:
                    self.notify(
                        "Enter a connection URI for the selected database.",
                        severity="error",
                    )
                    return
                from .domain import DomainScreen

                self.app.push_screen(DomainScreen())
