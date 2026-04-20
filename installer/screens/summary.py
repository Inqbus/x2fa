"""Summary screen — shown after a successful installation."""
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Collapsible, Footer, Header, Markdown, Static

_HELP_TEXT = """\
## Next Steps

Follow this checklist in order after the installer completes:

1. **Configure your reverse proxy** using the snippet shown below.
   - For `tls_client_auth`: the proxy must request and forward client certificates.
   - Restart / reload the proxy after updating its config.

2. **Start X2FA** with the command shown below.
   Verify it is reachable at `https://<domain>/.well-known/openid-configuration`.

3. **Configure your relying-party application** with:
   - `issuer`: `https://<domain>`
   - `client_id`: the Client ID you entered in the installer
   - `redirect_uri`: the Redirect URI you entered
   - For `tls_client_auth`: the `.cert.pem` and `.key.pem` files from the bundle above
   - For `client_secret_*`: the secret printed in the installation log

4. **Test the authentication flow** end-to-end before going live.

5. **Back up** `~/.config/x2fa/` and `~/.local/share/x2fa/ca_key.pem`.
   The CA private key is not stored in the database — losing it means you cannot
   issue new client certificates for this CA.

### Adding more clients later

```
flask add-client <client_id> <redirect_uri> --method tls_client_auth
flask issue-client-cert <client_id> --ca <ca_name> --output ./certs
```
"""

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
    BINDINGS = [("f1", "toggle_help", "Help")]

    def action_toggle_help(self) -> None:
        self.query_one("#help_panel", Collapsible).collapsed ^= True

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
            with Collapsible(title="Next Steps  (F1)", id="help_panel", collapsed=False):
                yield Markdown(_HELP_TEXT)

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
