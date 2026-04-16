"""Summary screen — shown after a successful installation."""
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Static

_PROXY_SNIPPETS = {
    "caddy": """\
2fa.example.com {{
    reverse_proxy localhost:5000
    tls {{
        # Automatic Let's Encrypt certificate
    }}
}}""",
    "nginx": """\
server {{
    listen 443 ssl http2;
    server_name {domain};

    ssl_certificate     /etc/letsencrypt/live/{domain}/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/{domain}/privkey.pem;

    # Optional client-cert verification (required for /token)
    ssl_verify_client optional;
    ssl_client_certificate {ca_cert};
    ssl_verify_depth 2;

    location /token {{
        ssl_verify_client on;
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Client-Certificate $ssl_client_cert;
    }}

    location / {{
        proxy_pass http://127.0.0.1:5000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-Proto $scheme;
    }}
}}""",
}


class SummaryScreen(Screen):
    def compose(self) -> ComposeResult:
        cfg = self.app.config

        proxy_snippet = _PROXY_SNIPPETS.get(cfg.proxy_type or "caddy", "").format(
            domain=cfg.domain or "2fa.example.com",
            ca_cert=cfg.effective_ca_cert() or "/etc/x2fa/ca_cert.pem",
        )

        yield Header()
        with Container(id="panel"):
            yield Static("[green bold]✓  Installation complete[/]", markup=True,
                         classes="screen-title")

            yield Static("Start command:", classes="field-label")
            yield Static(
                "  ENV_FOR_DYNACONF=production "
                "uv run gunicorn 'x2fa.wsgi:app' --bind 127.0.0.1:5000",
                classes="hint",
            )

            if cfg.generated_files:
                yield Static("Generated files:", classes="field-label")
                for f in cfg.generated_files:
                    yield Static(f"  {f}", classes="hint")

            if cfg.client_id and cfg.client_auth_method == "tls_client_auth":
                yield Static("Client certificate bundle:", classes="field-label")
                yield Static(
                    f"  Copy  {cfg.client_cert_output_dir}/{cfg.client_id}.cert.pem  "
                    f"and  .key.pem  to your application server.",
                    classes="hint",
                )

            if proxy_snippet:
                yield Static(
                    f"Reverse proxy config  ({cfg.proxy_type}):",
                    classes="field-label",
                )
                yield Static(proxy_snippet, classes="hint")

            yield Static("Next steps:", classes="field-label")
            yield Static(
                "  1. Configure and start your reverse proxy.\n"
                "  2. Start X2FA with the command above.\n"
                "  3. Configure your application with the OIDC client credentials.\n"
                "  4. Run `flask issue-client-cert <id> --ca <name>` to add more clients.",
                classes="hint",
            )

            with Container(id="buttons"):
                yield Button("Done", id="done", variant="success")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "done":
            self.app.exit()
