"""Summary screen — shown after a successful installation."""
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Collapsible, Footer, Header, Markdown, Static

from installer.screens.execute import _LogOverlay, _copy_to_clipboard

_HELP_TEXT = """\
## Installation Summary

### systemd service

The installer writes `~/.config/systemd/user/x2fa.service`.
Enable and start it with the commands shown in the **systemd** section below.

`loginctl enable-linger` ensures the service starts on boot even without an
interactive login — required for headless servers.

### Start command

Copy and run this command to start X2FA manually (without systemd).

### Generated files

Lists every file written during installation: CA key, CA cert, client cert, client key.
These paths are also printed in the Execute screen log.

**CA private key**: store it securely. It is only needed to issue new client certificates.
After copying it to a safe location, you may restrict its permissions to `0400`.

**Client cert + key**: copy both files to the relying-party application server.
The cert goes to the TLS client cert field; the key is the corresponding private key.

### Reverse proxy config

A ready-to-use configuration snippet for your chosen proxy. Paste it into your proxy's
config file and reload the proxy. For `tls_client_auth` the snippet includes the mTLS
`client_auth` / `ssl_verify_client` directives.

---

## Next Steps

Follow this checklist in order after the installer completes:

1. **Configure your reverse proxy** using the snippet shown below.
   - For `tls_client_auth`: the proxy must request and forward client certificates.
   - Restart / reload the proxy after updating its config.

2. **Enable X2FA** as a systemd user service (see the **systemd** section below).
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

            # systemd user service
            unit_path = cfg.config_root / ".config" / "systemd" / "user" / "x2fa.service"
            yield Static("systemd user service:", classes="field-label")
            yield Static(
                f"  {unit_path}\n"
                "\n"
                "  # Enable and start (runs as the current user):\n"
                "  systemctl --user daemon-reload\n"
                "  systemctl --user enable --now x2fa.service\n"
                "\n"
                "  # Auto-start on boot without interactive login (servers):\n"
                "  loginctl enable-linger",
                classes="hint",
            )

            yield Static("Manual start command (without systemd):", classes="field-label")
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
                "  1. Configure and reload your reverse proxy.\n"
                "  2. systemctl --user daemon-reload && systemctl --user enable --now x2fa.service\n"
                "  3. loginctl enable-linger  (headless servers — auto-start on boot)\n"
                "  4. Configure your application with the OIDC client credentials.\n"
                "  5. Run `flask issue-client-cert <id> --ca <name>` to add more clients.",
                classes="hint",
            )

            with Container(id="buttons"):
                yield Button("Copy summary", id="copy", variant="default")
                yield Button("Done", id="done", variant="success")
        yield Footer()

    def _build_summary_text(self) -> str:
        cfg = self.app.config
        proxy_snippet = _PROXY_SNIPPETS.get(cfg.proxy_type or "caddy", "").format(
            domain=cfg.domain or "2fa.example.com",
            ca_cert=cfg.effective_ca_cert() or "/etc/x2fa/ca_cert.pem",
        )
        unit_path = cfg.config_root / ".config" / "systemd" / "user" / "x2fa.service"

        lines = [
            "X2FA Installation Summary",
            "=" * 40,
            "",
            "systemd user service:",
            f"  {unit_path}",
            "",
            "  # Enable and start:",
            "  systemctl --user daemon-reload",
            "  systemctl --user enable --now x2fa.service",
            "",
            "  # Auto-start on boot without interactive login:",
            "  loginctl enable-linger",
            "",
            "Manual start command (without systemd):",
            "  ENV_FOR_DYNACONF=production uv run gunicorn 'x2fa.wsgi:app' --bind 127.0.0.1:5000",
        ]

        if cfg.generated_files:
            lines += ["", "Generated files:"]
            for f in cfg.generated_files:
                lines.append(f"  {f}")

        if cfg.client_id and cfg.client_auth_method == "tls_client_auth":
            lines += [
                "",
                "Client certificate bundle:",
                f"  {cfg.client_cert_output_dir}/{cfg.client_id}.cert.pem",
                f"  {cfg.client_cert_output_dir}/{cfg.client_id}.key.pem",
            ]

        if proxy_snippet:
            lines += ["", f"Reverse proxy config ({cfg.proxy_type}):", proxy_snippet]

        lines += [
            "",
            "Next steps:",
            "  1. Configure and reload your reverse proxy.",
            "  2. systemctl --user daemon-reload && systemctl --user enable --now x2fa.service",
            "  3. loginctl enable-linger  (headless servers — auto-start on boot)",
            "  4. Configure your application with the OIDC client credentials.",
            "  5. Run `flask issue-client-cert <id> --ca <name>` to add more clients.",
        ]

        return "\n".join(lines)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "copy":
                text = self._build_summary_text()
                if _copy_to_clipboard(text):
                    self.notify("Summary copied to clipboard.")
                else:
                    self.app.push_screen(_LogOverlay(text))
            case "done":
                self.app.exit()
