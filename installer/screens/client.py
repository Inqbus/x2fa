from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Collapsible, Footer, Header, Input, Markdown, RadioButton, RadioSet, Static

_PKI_CA_METHODS = {"tls_client_auth", "private_key_jwt"}
_SECRET_METHODS = {"client_secret_jwt", "client_secret_post", "client_secret_basic"}

_HELP_TEXT = """\
## Authentication method

Choose how the relying-party application identifies itself when it calls `/token`.

| Method | Trust model | Shared secret? | Recommended |
|---|---|---|---|
| `tls_client_auth` | CA-signed mTLS certificate | No | **Yes** |
| `private_key_jwt` | JWT signed with client's EC key, verified via JWKS | No | Yes |
| `self_signed_tls_client_auth` | SHA-256 fingerprint of a self-signed cert | No | Acceptable |
| `client_secret_jwt` | HMAC-signed JWT (HS256) | Yes | With caution |
| `client_secret_post` | Secret in POST body | Yes | No |
| `client_secret_basic` | HTTP Basic authentication | Yes | No |

**tls_client_auth** (recommended): The installer generates a CA and issues a client
certificate. The relying party presents it at `/token`; the reverse proxy verifies it
and forwards it in `X-Client-Certificate`. No secret is ever transmitted.

**private_key_jwt**: The relying party generates its own EC key pair and signs JWT
assertions with it. X2FA fetches the matching public key from the JWKS URI.
No certificate infrastructure is needed on the X2FA side.

**self_signed_tls_client_auth**: Provide the path to an existing self-signed certificate.
The installer pins its SHA-256 fingerprint. No CA is needed. Suitable when the client
already has a self-signed cert and you do not want to run a CA.

**client_secret_post / client_secret_basic**: A 64-char random secret is auto-generated
and printed once. The relying party sends it on every request. Only acceptable behind TLS.
Not recommended for production — a leaked secret immediately compromises the client.

**client_secret_jwt**: Like the above but wraps the secret in a signed JWT, adding a
nonce and expiry to each request. Preferable to `_post`/`_basic` when a shared secret
is unavoidable.
"""


def _show(visible: bool, *base_classes: str) -> str:
    """Returns CSS classes with 'hidden' appended when not visible."""
    base = " ".join(c for c in base_classes if c)
    return base if visible else f"{base} hidden".strip()


class ClientScreen(Screen):
    BINDINGS = [("f1", "toggle_help", "Help")]

    def action_toggle_help(self) -> None:
        self.query_one("#help_panel", Collapsible).collapsed ^= True

    def compose(self) -> ComposeResult:
        cfg = self.app.config
        method = cfg.client_auth_method or "tls_client_auth"

        is_tls    = method == "tls_client_auth"
        is_jwt    = method == "private_key_jwt"
        is_ss     = method == "self_signed_tls_client_auth"
        is_secret = method in _SECRET_METHODS

        yield Header()
        with Container(id="panel"):
            yield Static("First OIDC Client", classes="screen-title")
            with Collapsible(title="Help  (F1)", id="help_panel", collapsed=True):
                yield Markdown(_HELP_TEXT)
            yield Static(
                "[dim]Register the first relying-party app. "
                "Additional clients can be added later with `flask add-client`.[/]  "
                "[dim]* Required[/]",
                markup=True, classes="hint",
            )

            yield Static("Client ID (typically the app domain) [bold red]*[/]:", markup=True, classes="field-label")
            yield Input(value=cfg.client_id, placeholder="shop.example.com", id="client_id")

            yield Static("Redirect URI [bold red]*[/]:", markup=True, classes="field-label")
            yield Input(
                value=cfg.client_redirect_uri,
                placeholder="https://shop.example.com/auth/callback",
                id="redirect_uri",
            )

            yield Static("Authentication method:", classes="field-label")
            with RadioSet(id="auth_method"):
                yield RadioButton(
                    "tls_client_auth              — CA-signed mTLS  [recommended]",
                    id="tls_client_auth", value=is_tls,
                )
                yield RadioButton(
                    "private_key_jwt              — JWKS-verified JWT",
                    id="private_key_jwt", value=is_jwt,
                )
                yield RadioButton(
                    "self_signed_tls_client_auth  — fingerprint-pinned self-signed cert",
                    id="self_signed_tls_client_auth", value=is_ss,
                )
                yield RadioButton(
                    "client_secret_jwt            — HMAC-signed JWT",
                    id="client_secret_jwt", value=method == "client_secret_jwt",
                )
                yield RadioButton(
                    "client_secret_post           — secret in POST body  [⚠ not for production]",
                    id="client_secret_post", value=method == "client_secret_post",
                )
                yield RadioButton(
                    "client_secret_basic          — HTTP Basic auth  [⚠ not for production]",
                    id="client_secret_basic", value=method == "client_secret_basic",
                )

            # ── tls_client_auth ────────────────────────────────────────────
            yield Static("Certificate output directory:", id="cert_dir_label",
                         classes=_show(is_tls, "field-label"))
            yield Input(
                value=cfg.client_cert_output_dir or ".",
                placeholder="./certs",
                id="cert_out_dir",
                classes=_show(is_tls),
            )
            yield Static(
                "[dim]The installer issues a client cert signed by the CA configured in the next step.[/]",
                id="cert_hint", markup=True,
                classes=_show(is_tls, "hint"),
            )

            # ── private_key_jwt ───────────────────────────────────────────
            yield Static("JWKS URI [bold red]*[/]:", id="jwks_label", markup=True,
                         classes=_show(is_jwt, "field-label"))
            yield Input(
                value=cfg.client_jwks_uri,
                placeholder="https://shop.example.com/.well-known/jwks.json",
                id="jwks_uri",
                classes=_show(is_jwt),
            )

            # ── self_signed_tls_client_auth ────────────────────────────────
            yield Static("Self-signed certificate (PEM) [bold red]*[/]:", id="ss_cert_label", markup=True,
                         classes=_show(is_ss, "field-label"))
            yield Input(
                value=cfg.client_self_signed_cert_path,
                placeholder="/path/to/client_self_signed.pem",
                id="ss_cert_path",
                classes=_show(is_ss),
            )
            yield Static(
                "[dim]X2FA will pin the SHA-256 fingerprint of this certificate. "
                "No CA infrastructure required.[/]",
                id="ss_cert_hint", markup=True,
                classes=_show(is_ss, "hint"),
            )

            # ── client_secret_* ───────────────────────────────────────────
            yield Static(
                "[dim]A 64-character random secret will be generated automatically "
                "and printed in the installation log. Record it before closing "
                "the installer — it is not stored in plaintext.[/]",
                id="secret_hint", markup=True,
                classes=_show(is_secret, "hint"),
            )

            with Container(id="buttons"):
                yield Button("← Back", id="back")
                yield Button("Continue →", id="next", variant="primary")
        yield Footer()

    # ── Events ────────────────────────────────────────────────────────────

    def on_radio_set_changed(self, event: RadioSet.Changed) -> None:
        if event.radio_set.id != "auth_method":
            return
        method = event.pressed.id
        self.app.config.client_auth_method = method

        is_tls    = method == "tls_client_auth"
        is_jwt    = method == "private_key_jwt"
        is_ss     = method == "self_signed_tls_client_auth"
        is_secret = method in _SECRET_METHODS

        for wid in ("#cert_dir_label", "#cert_out_dir", "#cert_hint"):
            self.query_one(wid).set_class(not is_tls, "hidden")
        for wid in ("#jwks_label", "#jwks_uri"):
            self.query_one(wid).set_class(not is_jwt, "hidden")
        for wid in ("#ss_cert_label", "#ss_cert_path", "#ss_cert_hint"):
            self.query_one(wid).set_class(not is_ss, "hidden")
        self.query_one("#secret_hint").set_class(not is_secret, "hidden")

    def on_input_changed(self, event: Input.Changed) -> None:
        cfg = self.app.config
        match event.input.id:
            case "client_id":    cfg.client_id                    = event.value
            case "redirect_uri": cfg.client_redirect_uri          = event.value
            case "jwks_uri":     cfg.client_jwks_uri              = event.value
            case "cert_out_dir": cfg.client_cert_output_dir       = event.value
            case "ss_cert_path": cfg.client_self_signed_cert_path = event.value

    def _validate(self) -> bool:
        cfg = self.app.config
        if not cfg.client_id:
            self.notify("Client ID is required.", severity="error")
            return False
        if not cfg.client_redirect_uri:
            self.notify("Redirect URI is required.", severity="error")
            return False
        if cfg.client_auth_method == "private_key_jwt" and not cfg.client_jwks_uri:
            self.notify("JWKS URI is required for private_key_jwt.", severity="error")
            return False
        if (cfg.client_auth_method == "self_signed_tls_client_auth"
                and not cfg.client_self_signed_cert_path):
            self.notify(
                "Certificate path is required for self_signed_tls_client_auth.",
                severity="error",
            )
            return False
        return True

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "back":
                self.app.pop_screen()
            case "next":
                if not self._validate():
                    return
                if self.app.config.client_auth_method in _PKI_CA_METHODS:
                    from installer.screens.ca_setup import CASetupScreen
                    self.app.push_screen(CASetupScreen())
                else:
                    from installer.screens.review import ReviewScreen
                    self.app.push_screen(ReviewScreen())
