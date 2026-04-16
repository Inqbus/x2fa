from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Select, Static

_PROXY_HINTS = {
    "caddy":   "Automatic HTTPS (Let's Encrypt). Add to Caddyfile:\n  2fa.example.com { reverse_proxy localhost:5000 }",
    "nginx":   "Manual TLS config. An nginx snippet with mTLS settings will be shown in the summary.",
    "traefik": "Label-based discovery. See Traefik docs for TLS + clientAuth options.",
    "other":   "Configure your proxy to forward HTTP to localhost:5000.",
}


class DomainScreen(Screen):
    def compose(self) -> ComposeResult:
        cfg = self.app.config
        proxy = cfg.proxy_type or "caddy"
        yield Header()
        with Container(id="panel"):
            yield Static("Domain & Reverse Proxy", classes="screen-title")

            yield Static("Domain (no https://, no trailing slash):", classes="field-label")
            yield Input(value=cfg.domain, placeholder="2fa.example.com", id="domain")

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
            self.app.config.domain = event.value.strip()

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
                from .security import SecurityScreen
                self.app.push_screen(SecurityScreen())
