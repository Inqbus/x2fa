import secrets

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Collapsible, Footer, Header, Input, Markdown, Static

_HELP_TEXT = """\
## Security

### SECRET_KEY

A 64-character (256-bit) random hex value used to:
- Sign and verify Flask session cookies
- Encrypt stored TOTP secrets (Fernet symmetric encryption)
- Sign authorization codes

**Changing this after installation invalidates all active user sessions and all
stored TOTP secrets** — users will need to re-enroll their authenticators.
Keep this value secret and back it up.

### SECRET_SALT

A 32-character (128-bit) random hex value used to pseudonymise IP addresses in the
audit log. Combined with the IP address via HMAC before storage, so audit entries
cannot be reverse-mapped to real IPs without the salt.

Changing this after installation does not break active sessions, but existing audit log
entries will no longer correctly correlate to the same IP addresses.

### Rate limiting

X2FA rate-limits authentication endpoints to slow credential-stuffing attacks.

**memory://** (default): Rate limit counters are stored in process memory. This works
correctly when X2FA runs as a single process. If you run multiple Gunicorn workers,
each worker has its own counters — limits are not shared across workers.

**Redis**: Required when running `--workers > 1`. All workers share one counter store,
so limits are enforced correctly across the full process pool.

Redis URI format: `redis://localhost:6379/0`
"""


class SecurityScreen(Screen):
    BINDINGS = [("f1", "toggle_help", "Help")]

    def action_toggle_help(self) -> None:
        self.query_one("#help_panel", Collapsible).collapsed ^= True

    def compose(self) -> ComposeResult:
        cfg = self.app.config
        yield Header()
        with Container(id="panel"):
            yield Static("Security", classes="screen-title")
            with Collapsible(title="Help  (F1)", id="help_panel", collapsed=True):
                yield Markdown(_HELP_TEXT)

            yield Static("SECRET_KEY  (64 hex chars — auto-generated):", classes="field-label")
            yield Input(value=cfg.secret_key, id="secret_key")
            yield Static(
                "[dim]Changing this after install invalidates all sessions and encrypted TOTP secrets.[/]",
                markup=True, classes="hint",
            )

            yield Static("SECRET_SALT  (32 hex chars — auto-generated):", classes="field-label")
            yield Input(value=cfg.secret_salt, id="secret_salt")
            yield Static(
                "[dim]Used for IP anonymisation in the audit log. Keep secret.[/]",
                markup=True, classes="hint",
            )

            yield Static("", classes="section-sep")
            yield Static("Rate limiting:", classes="field-label")
            yield Checkbox(
                "Use Redis (required when running multiple Gunicorn workers)",
                value=cfg.use_redis,
                id="use_redis",
            )
            redis_cls = "field-label" if cfg.use_redis else "field-label hidden"
            yield Static("Redis URI:", id="redis_label", classes=redis_cls)
            yield Input(
                value=cfg.redis_uri,
                placeholder="redis://localhost:6379/0",
                id="redis_uri",
                classes="" if cfg.use_redis else "hidden",
            )

            yield Button("↻  Regenerate keys", id="regen", variant="default")

            with Container(id="buttons"):
                yield Button("← Back", id="back")
                yield Button("Continue →", id="next", variant="primary")
        yield Footer()

    def on_mount(self) -> None:
        cfg = self.app.config
        if not cfg.secret_key:
            cfg.secret_key = secrets.token_hex(32)
            self.query_one("#secret_key", Input).value = cfg.secret_key
        if not cfg.secret_salt:
            cfg.secret_salt = secrets.token_hex(16)
            self.query_one("#secret_salt", Input).value = cfg.secret_salt

    # ── Events ────────────────────────────────────────────────────────────

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "use_redis":
            self.app.config.use_redis = event.value
            for wid in ("#redis_label", "#redis_uri"):
                self.query_one(wid).set_class(not event.value, "hidden")

    def on_input_changed(self, event: Input.Changed) -> None:
        match event.input.id:
            case "secret_key":  self.app.config.secret_key  = event.value
            case "secret_salt": self.app.config.secret_salt = event.value
            case "redis_uri":   self.app.config.redis_uri   = event.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "regen":
                cfg = self.app.config
                cfg.secret_key  = secrets.token_hex(32)
                cfg.secret_salt = secrets.token_hex(16)
                self.query_one("#secret_key",  Input).value = cfg.secret_key
                self.query_one("#secret_salt", Input).value = cfg.secret_salt
                self.notify("Keys regenerated.", severity="information")
            case "back":
                self.app.pop_screen()
            case "next":
                cfg = self.app.config
                if not cfg.secret_key or not cfg.secret_salt:
                    self.notify("Keys cannot be empty.", severity="error")
                    return
                from .client import ClientScreen
                self.app.push_screen(ClientScreen())
