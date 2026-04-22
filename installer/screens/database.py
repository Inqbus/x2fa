from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Collapsible, Footer, Header, Input, Markdown, RadioButton, RadioSet, Static

_HELP_TEXT = """\
## Database

X2FA stores users, credentials, OIDC clients, and audit events in a relational database.

### SQLite (default)

Zero configuration. The database is a single file stored at
`~/.local/share/x2fa/db.sqlite` (or inside `--x2fa-home` if set).

**Limitations:**
- Only one writer at a time — suitable for a single Gunicorn process or low-traffic
  multi-worker setups
- No built-in replication or high-availability
- Suitable for most single-server deployments (up to ~50k users)

### PostgreSQL

Recommended for high-availability or multi-server deployments. Requires the optional
`postgres` extra — install it before running the installer:
```
uv sync --extra postgres
```
Connection URI format: `postgresql://user:password@host/dbname`

### MySQL / MariaDB

Supported via `pymysql`. Install with:
```
uv sync --extra mysql
```
Connection URI format: `mysql+pymysql://user:password@host/dbname`

### Connection URI

Shown when PostgreSQL or MySQL is selected. Provide the full SQLAlchemy connection
string including credentials, host, port, and database name.

| Backend | Example URI |
|---|---|
| PostgreSQL | `postgresql://x2fa:pass@localhost/x2fa` |
| MySQL | `mysql+pymysql://x2fa:pass@localhost/x2fa` |

The database and user must already exist. The installer does not create them.

### Schema management

The installer runs `flask init-db` which calls Alembic `upgrade head` to create all
tables. On existing installations, use `flask db-upgrade` instead — it applies only
the missing migrations without touching existing data.
"""


class DatabaseScreen(Screen):
    BINDINGS = [("f1", "toggle_help", "Help")]

    def action_toggle_help(self) -> None:
        self.query_one("#help_panel", Collapsible).collapsed ^= True

    def compose(self) -> ComposeResult:
        cfg = self.app.config
        db = cfg.db_type or "sqlite"
        yield Header()
        with Container(id="panel"):
            yield Static("Database", classes="screen-title")
            with Collapsible(title="Help  (F1)", id="help_panel", collapsed=True):
                yield Markdown(_HELP_TEXT)
            yield Static("[dim]* Required[/]", markup=True,
                         classes="hint" if db != "sqlite" else "hint hidden",
                         id="req_legend")
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
                "Connection URI [bold red]*[/]:",
                id="uri_label",
                markup=True,
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
        self.query_one("#req_legend").set_class(sqlite, "hidden")
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
                from installer.screens.domain import DomainScreen

                self.app.push_screen(DomainScreen())
