from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Collapsible, Footer, Header, Input, Markdown, Select, Static

_PROXY_HINTS = {
    "caddy":   "Automatic HTTPS (Let's Encrypt). Add to Caddyfile:\n  2fa.example.com { reverse_proxy localhost:5000 }",
    "nginx":   "Manual TLS config. An nginx snippet with mTLS settings will be shown in the summary.",
    "traefik": "Label-based discovery. See Traefik docs for TLS + clientAuth options.",
    "other":   "Configure your proxy to forward HTTP to localhost:5000.",
}

_HELP_TEXT = """\
## Domain & Reverse Proxy

### Domain

Enter the public hostname where X2FA will be reachable — no `https://` prefix and no
trailing slash. For example: `2fa.myapp.io`.

The installer derives `ORIGIN = https://<domain>` automatically. The ORIGIN value is
embedded in the OIDC discovery document and must exactly match the URL clients use.

### Reverse proxy

X2FA itself speaks plain HTTP on `localhost:5000`. TLS termination and (optionally)
mTLS client certificate verification are handled by the reverse proxy.

| Proxy | TLS | mTLS client cert support |
|---|---|---|
| Caddy | Automatic (Let's Encrypt) | Via `client_auth` block |
| nginx | Manual certificate | Via `ssl_verify_client` + `ssl_client_certificate` |
| Traefik | Via router TLS config | Via `clientAuth` middleware |
| Other | Manual | Manual |

For `tls_client_auth`, the proxy must:
1. Request a client certificate from the relying party
2. Verify it against the X2FA CA certificate
3. Forward it as the `X-Client-Certificate` header to X2FA

The installer's Summary screen shows a ready-to-use proxy configuration snippet.
"""


class DomainScreen(Screen):
    BINDINGS = [("f1", "toggle_help", "Help")]

    def action_toggle_help(self) -> None:
        self.query_one("#help_panel", Collapsible).collapsed ^= True

    def compose(self) -> ComposeResult:
        cfg = self.app.config
        proxy = cfg.proxy_type or "caddy"
        origin_hint = f"[dim]ORIGIN will be: https://{cfg.domain}[/]" if cfg.domain else "[dim]Enter a domain name.[/]"
        yield Header()
        with Container(id="panel"):
            yield Static("Domain & Reverse Proxy", classes="screen-title")
            with Collapsible(title="Help  (F1)", id="help_panel", collapsed=True):
                yield Markdown(_HELP_TEXT)
            yield Static("[dim]* Required[/]", markup=True, classes="hint")

            yield Static("Domain (no https://, no trailing slash) [bold red]*[/]:", markup=True, classes="field-label")
            yield Input(value=cfg.domain, placeholder="2fa.example.com", id="domain")
            yield Static(origin_hint, id="origin_hint", markup=True, classes="hint")

            yield Static("Reverse proxy:", classes="field-label")
            yield Select(
                options=[
                    ("Caddy  (recommended, auto-HTTPS)", "caddy"),
                    ("nginx",                            "nginx"),
                    ("Traefik",                          "traefik"),
                    ("Other",                            "other"),
                ],
                value=proxy,
                id="proxy",
            )
            yield Static(_PROXY_HINTS[proxy], id="proxy_hint", classes="hint")

            with Container(id="buttons"):
                yield Button("← Back", id="back")
                yield Button("Continue →", id="next", variant="primary")
        yield Footer()

    # ── Events ────────────────────────────────────────────────────────────

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "domain":
            val = event.value.strip()
            self.app.config.domain = val
            origin = f"[dim]ORIGIN will be: https://{val}[/]" if val else "[dim]Enter a domain name.[/]"
            self.query_one("#origin_hint", Static).update(origin)

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "proxy" and event.value is not Select.BLANK:
            val = str(event.value)
            self.app.config.proxy_type = val
            self.query_one("#proxy_hint", Static).update(_PROXY_HINTS.get(val, ""))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "back":
                self.app.pop_screen()
            case "next":
                if not self.app.config.domain:
                    self.notify("Enter a domain name.", severity="error")
                    return
                from installer.screens.security import SecurityScreen
                self.app.push_screen(SecurityScreen())
