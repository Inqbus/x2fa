from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Collapsible, Footer, Header, Input, Markdown, RadioButton, RadioSet, Static

_HELP_TEXT = """\
## Certificate Authority setup

A Certificate Authority (CA) is required for `tls_client_auth` and `private_key_jwt`.
X2FA uses the CA to issue client certificates and to verify them at the `/token` endpoint.

### Generate vs Import

**Generate new CA** (recommended for most installations): The installer creates a new
EC-P256 self-signed CA key and certificate. Keep the private key offline after install —
it is only needed when issuing new client certificates.

**Import existing CA**: Use this when you already have a CA (e.g. an enterprise PKI or
HSM-backed CA). Only the certificate (PEM) is imported; the private key stays with you.
When you need to issue a new client certificate later, run:
```
flask issue-client-cert <client_id> --ca <name>
```
and supply the CA key path interactively.

### CA Common Name (CN)

Use a descriptive human-readable name, **not** a hostname. Examples:
- `MyApp Internal CA`
- `Acme Corp X2FA CA`

The CN appears in client certificate chains and in `flask list-cas` output.

### Validity

Longer validity = less maintenance burden. Shorter = better rotation hygiene.

| Value | Duration | Recommendation |
|---|---|---|
| 365 | 1 year | Too short for a CA; prefer ≥ 3 years |
| 1825 | 5 years | Good default for internal use |
| 3650 | 10 years | Reasonable for offline root CAs |
| 7300 | 20 years | Maximum recommended |

When a CA expires, existing mTLS connections stop working immediately. Plan renewal
before expiry — the `Manage CAs` main-menu option handles this without reinstalling.

### Key and certificate paths

The CA private key must be **readable only by the X2FA process user** (mode 0600).
The CA certificate must be **readable by the reverse proxy** to verify client certs.

Typical locations:
- Running as root: `/etc/x2fa/ca_key.pem` and `/etc/x2fa/ca_cert.pem`
- Running as a user: `~/.local/share/x2fa/ca_key.pem` and `~/.local/share/x2fa/ca_cert.pem`
"""


class CASetupScreen(Screen):
    BINDINGS = [("f1", "toggle_help", "Help")]

    def action_toggle_help(self) -> None:
        self.query_one("#help_panel", Collapsible).collapsed ^= True

    def compose(self) -> ComposeResult:
        cfg = self.app.config
        action = cfg.ca_action or "generate"
        gen_cls = "" if action == "generate" else "hidden"
        imp_cls = "hidden" if action == "generate" else ""

        yield Header()
        with Container(id="panel"):
            yield Static("Certificate Authority", classes="screen-title")
            with Collapsible(title="Help  (F1)", id="help_panel", collapsed=True):
                yield Markdown(_HELP_TEXT)
            yield Static("[dim]* Required[/]", markup=True, classes="hint")

            yield Static("Action:", classes="field-label")
            with RadioSet(id="ca_action"):
                yield RadioButton(
                    "Generate new self-signed CA  (recommended)",
                    id="generate",
                    value=action == "generate",
                )
                yield RadioButton(
                    "Import existing CA certificate",
                    id="import",
                    value=action == "import",
                )

            # ── Generate fields ────────────────────────────────────────────
            with Container(id="gen_fields", classes=gen_cls):
                yield Static("CA name (used in flask CLI) [bold red]*[/]:", markup=True, classes="field-label")
                yield Input(
                    value=cfg.ca_name, placeholder="x2fa-internal-ca", id="ca_name"
                )

                yield Static("Common Name (CN):", classes="field-label")
                yield Input(value=cfg.ca_cn, placeholder="X2FA Internal CA", id="ca_cn")

                yield Static("Validity (days):", classes="field-label")
                yield Input(
                    value=str(cfg.ca_validity_days),
                    placeholder="3650",
                    id="ca_validity_days",
                )
                yield Static(
                    _validity_hint(cfg.ca_validity_days),
                    id="validity_hint",
                    markup=True,
                    classes="hint",
                )

                hint = (
                    "[dim]Root: /etc/x2fa | User: ~/.x2fa [/]"
                    if cfg.ca_key_path.startswith(("/etc", str(Path.home())))
                    else "[dim]Keep offline after install.[/]"
                )
                yield Static("Private key output path [bold red]*[/]:", markup=True, classes="field-label")
                yield Input(
                    value=cfg.ca_key_path,
                    placeholder="/etc/x2fa/ca_key.pem",
                    id="ca_key_path",
                )
                yield Static(hint, markup=True, classes="hint")

                hint = (
                    "[dim]Root: /etc/x2fa | User: ~/.x2fa [/]"
                    if cfg.ca_cert_path.startswith(("/etc", str(Path.home())))
                    else ""
                )
                yield Static("Certificate output path [bold red]*[/]:", markup=True, classes="field-label")
                yield Input(
                    value=cfg.ca_cert_path,
                    placeholder="/etc/x2fa/ca_cert.pem",
                    id="ca_cert_path",
                )
                yield Static(hint, markup=True, classes="hint")

            # ── Import fields ──────────────────────────────────────────────
            with Container(id="imp_fields", classes=imp_cls):
                yield Static("CA name (used in flask CLI) [bold red]*[/]:", markup=True, classes="field-label")
                yield Input(
                    value=cfg.ca_name, placeholder="x2fa-internal-ca", id="ca_name_imp"
                )

                yield Static(
                    "Path to existing CA certificate (PEM) [bold red]*[/]:", markup=True, classes="field-label"
                )
                yield Input(
                    value=cfg.ca_import_path,
                    placeholder="/path/to/ca.pem",
                    id="ca_import_path",
                )
                yield Static(
                    "[dim]The CA private key is never stored by X2FA.\n"
                    "You only need it when issuing new client certificates.[/]",
                    markup=True,
                    classes="hint",
                )

            with Container(id="buttons"):
                yield Button("← Back", id="back")
                yield Button("Continue →", id="next", variant="primary")
        yield Footer()

    # ── Events ────────────────────────────────────────────────────────────

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id != "ca_action":
            return
        action = event.pressed.id
        self.app.config.ca_action = action
        self.query_one("#gen_fields").set_class(action != "generate", "hidden")
        self.query_one("#imp_fields").set_class(action != "import", "hidden")

    def on_input_changed(self, event: Input.Changed) -> None:
        cfg = self.app.config
        match event.input.id:
            case "ca_name" | "ca_name_imp":
                cfg.ca_name = event.value
            case "ca_cn":
                cfg.ca_cn = event.value
            case "ca_validity_days":
                try:
                    cfg.ca_validity_days = int(event.value)
                    self.query_one("#validity_hint", Static).update(
                        _validity_hint(cfg.ca_validity_days)
                    )
                except ValueError:
                    self.query_one("#validity_hint", Static).update(
                        "[dim]Enter a number of days.[/]"
                    )
            case "ca_key_path":
                cfg.ca_key_path = event.value
            case "ca_cert_path":
                cfg.ca_cert_path = event.value
            case "ca_import_path":
                cfg.ca_import_path = event.value

    def _validate(self) -> bool:
        cfg = self.app.config
        if not cfg.ca_name:
            self.notify("CA name is required.", severity="error")
            return False
        if cfg.ca_action == "generate":
            if not cfg.ca_key_path or not cfg.ca_cert_path:
                self.notify("Key and certificate paths are required.", severity="error")
                return False
        else:
            if not cfg.ca_import_path:
                self.notify("CA certificate path is required.", severity="error")
                return False
        return True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "back":
                self.app.pop_screen()
            case "next":
                if self._validate():
                    from installer.screens.review import ReviewScreen
                    self.app.push_screen(ReviewScreen())


def _validity_hint(days: int) -> str:
    if days <= 0:
        return "[dim]Enter a number of days.[/]"
    years = days / 365
    warn = (
        "  [yellow]⚠ Short validity — CA expires quickly, consider ≥ 365 days[/]"
        if days < 365
        else ""
    )
    return f"[dim]≈ {years:.1f} years{warn}[/]"
