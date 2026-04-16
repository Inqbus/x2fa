from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, RadioButton, RadioSet, Static


class CASetupScreen(Screen):
    def compose(self) -> ComposeResult:
        cfg = self.app.config
        action = cfg.ca_action or "generate"
        gen_cls = "" if action == "generate" else "hidden"
        imp_cls = "hidden" if action == "generate" else ""

        yield Header()
        with Container(id="panel"):
            yield Static("Certificate Authority", classes="screen-title")
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
                yield Static("CA name (used in flask CLI):", classes="field-label")
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

                hint = (
                    "[dim]Root: /etc/x2fa | User: ~/.x2fa [/]"
                    if cfg.ca_key_path.startswith(("/etc", str(Path.home())))
                    else "[dim]Keep offline after install.[/]"
                )
                yield Static("Private key output path:", classes="field-label")
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
                yield Static("Certificate output path:", classes="field-label")
                yield Input(
                    value=cfg.ca_cert_path,
                    placeholder="/etc/x2fa/ca_cert.pem",
                    id="ca_cert_path",
                )
                yield Static(hint, markup=True, classes="hint")

            # ── Import fields ──────────────────────────────────────────────
            with Container(id="imp_fields", classes=imp_cls):
                yield Static("CA name (used in flask CLI):", classes="field-label")
                yield Input(
                    value=cfg.ca_name, placeholder="x2fa-internal-ca", id="ca_name_imp"
                )

                yield Static(
                    "Path to existing CA certificate (PEM):", classes="field-label"
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
                except ValueError:
                    pass
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
                    from .execute import ExecuteScreen

                    self.app.push_screen(ExecuteScreen())
