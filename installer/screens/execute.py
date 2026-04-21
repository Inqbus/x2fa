"""Execute screen — runs all install steps sequentially with live progress output."""

import re
import subprocess

from textual import work
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Collapsible, Footer, Header, Log, Markdown, Static, TextArea

_PKI_CA_METHODS = {"tls_client_auth", "private_key_jwt"}

_STEPS = [
    ("config", "Write configuration files"),
    ("systemd", "Write systemd user service"),
    ("initdb", "Initialize database"),
    ("initkeys", "Generate signing keys"),
    ("ca", "Set up Certificate Authority"),
    ("add_ca", "Register CA in X2FA"),
    ("client", "Register OIDC client"),
    ("cert", "Issue client certificate"),
    ("systemd_activate", "Enable systemd service"),
]

_ICONS = {
    "pending": "[dim]○[/]",
    "running": "[yellow]▶[/]",
    "ok": "[green]✓[/]",
    "warn": "[yellow]⚠[/]",
    "error": "[red]✗[/]",
    "skip": "[dim]–[/]",
}


_HELP_TEXT = """\
## Installation Steps

| Step | What it does | Idempotent? |
|---|---|---|
| Write configuration files | Writes `x2fa_config.toml`, `security_config.toml`, `db_config.toml`, and `ratelimit_config.toml` to `~/.config/x2fa/` | Yes — overwrites |
| Write systemd user service | Writes `~/.config/systemd/user/x2fa.service` | Yes — overwrites |
| Initialize database | Runs `flask init-db` → Alembic `upgrade head` (creates all tables) | Yes on fresh DB; safe on existing DB |
| Generate signing keys | Runs `flask init-keys` → writes EC key pair to `~/.local/share/x2fa/` | Skips if key already exists |
| Set up Certificate Authority | Generates or imports the CA key and certificate | Overwrites on generate |
| Register CA in X2FA | Runs `flask add-ca` to store the CA cert in the database | Fails if name already registered |
| Register OIDC client | Runs `flask add-client` with the chosen auth method | Fails if client_id already registered |
| Issue client certificate | Runs `flask issue-client-cert` (tls_client_auth only) | Creates new cert each run |

### Recovering from a failed step

If a step fails, the error message is shown in the log below.
The most common causes:

- **Write configuration files**: Permission error — check that `~/.config/x2fa/` is
  writable by the current user.
- **Initialize database**: Connection refused for PostgreSQL/MySQL — verify the URI
  and that the database server is running.
- **Register CA / client**: Already registered — safe to ignore if re-running the
  installer on an existing installation. Use `flask revoke-ca` or `flask revoke-client`
  first if you want to replace an existing entry.
- **Issue client certificate**: CA key not found or not readable — verify the key path.
"""


class ExecuteScreen(Screen):
    BINDINGS = [("f1", "toggle_help", "Help")]

    def action_toggle_help(self) -> None:
        self.query_one("#help_panel", Collapsible).collapsed ^= True

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="panel"):
            yield Static("Installing X2FA", classes="screen-title")
            with Collapsible(title="Help  (F1)", id="help_panel", collapsed=True):
                yield Markdown(_HELP_TEXT)
            with Container(id="steps"):
                for step_id, label in _STEPS:
                    yield Static(
                        f"  {_ICONS['pending']}  {label}",
                        id=f"step-{step_id}",
                        markup=True,
                    )
            yield Log(id="log", auto_scroll=True, highlight=True)
            with Container(id="buttons"):
                yield Button("Copy log", id="copy", variant="default")
                yield Button("← Back",  id="back", variant="default")
                yield Button("↺ Retry", id="retry", variant="warning", disabled=True)
                yield Button("Abort",   id="abort", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        self._log = self.query_one("#log", Log)
        self._plain_lines: list[str] = []
        self._run_installation()

    # ── UI helpers (must be called on the main thread) ────────────────────

    def _set_step(self, step_id: str, status: str, label: str) -> None:
        self.query_one(f"#step-{step_id}", Static).update(
            f"  {_ICONS[status]}  {label}"
        )

    def _write(self, line: str) -> None:
        self._log.write_line(line)
        # Strip Rich markup tags for the plain-text clipboard copy.
        self._plain_lines.append(re.sub(r"\[/?[^\]]*\]", "", line))

    def _on_done(self) -> None:
        from installer.screens.summary import SummaryScreen

        self.app.push_screen(SummaryScreen())

    def _on_error(self, step_id: str, label: str, message: str) -> None:
        self._write(f"\n[red bold]Failed:[/] {label}")
        self._write(f"[red]{message}[/]")
        self.query_one("#abort", Button).label = "Quit"
        self.query_one("#retry", Button).disabled = False

    # ── Background worker ─────────────────────────────────────────────────

    @work(thread=True)
    def _run_installation(self) -> None:
        from installer.ca import generate_ca, issue_client_cert
        from installer.config_writer import write_configs, write_systemd_unit
        from installer.runner import add_ca, add_client, init_db, init_keys

        cfg = self.app.config
        method = cfg.client_auth_method
        needs_ca = method in _PKI_CA_METHODS

        def set_step(sid, status, lbl):
            self.app.call_from_thread(self._set_step, sid, status, lbl)

        def log(text):
            self.app.call_from_thread(self._write, text)

        def run(step_id: str, label: str, fn) -> bool:
            set_step(step_id, "running", label)
            try:
                ok, output = fn()
            except Exception as exc:
                ok, output = False, str(exc)
            for line in (output or "").splitlines():
                log(f"  {line}")
            set_step(step_id, "ok" if ok else "error", label)
            if not ok:
                self.app.call_from_thread(self._on_error, step_id, label, output or "")
            return ok

        # 1 — Config files
        if not run("config", "Write configuration files", lambda: write_configs(cfg)):
            return

        # 2 — systemd user service
        if not run("systemd", "Write systemd user service", lambda: write_systemd_unit(cfg)):
            return

        # 4 — init-db
        if not run("initdb", "Initialize database", lambda: init_db(cfg.install_root)):
            return

        # 5 — init-keys
        if not run(
            "initkeys", "Generate signing keys", lambda: init_keys(cfg.install_root)
        ):
            return

        # 6 — CA  (PKI methods only)
        ca_cert = None
        if needs_ca:
            if cfg.ca_action == "generate":

                def do_ca():
                    try:
                        generate_ca(
                            cfg.ca_cn,
                            cfg.ca_validity_days,
                            cfg.ca_key_path,
                            cfg.ca_cert_path,
                        )
                        return True, (
                            f"Key:  {cfg.ca_key_path}  (mode 0600)\n"
                            f"Cert: {cfg.ca_cert_path}"
                        )
                    except Exception as exc:
                        return False, str(exc)

                if not run("ca", "Generate CA certificate", do_ca):
                    return
            else:
                set_step("ca", "skip", f"CA: using existing  {cfg.ca_import_path}")

            # 5 — flask add-ca
            ca_cert = cfg.effective_ca_cert()
            if not run(
                "add_ca",
                "Register CA in X2FA",
                lambda: add_ca(cfg.ca_name, ca_cert, cfg.install_root),
            ):
                return
        else:
            set_step("ca", "skip", "CA setup  (not needed for this auth method)")
            set_step("add_ca", "skip", "Register CA  (skipped)")

        # 6 — flask add-client
        if cfg.client_id:

            def do_client():
                cert = (
                    cfg.client_self_signed_cert_path
                    if method == "self_signed_tls_client_auth"
                    else None
                )
                return add_client(
                    cfg.client_id,
                    cfg.client_redirect_uri,
                    method,
                    cfg.install_root,
                    jwks_uri=cfg.client_jwks_uri or None,
                    cert=cert,
                )

            # Run add-client and capture output to extract the plaintext secret
            # for the summary screen.
            _client_result: list[tuple[bool, str]] = []

            def do_client_capturing():
                result = do_client()
                _client_result.append(result)
                return result

            if not run("client", "Register OIDC client", do_client_capturing):
                return
            if _client_result:
                _, client_out = _client_result[0]
                # CLI prints: "Client secret: <hex>  <- record this now..."
                for line in (client_out or "").splitlines():
                    if line.startswith("Client secret:"):
                        cfg.client_secret = line.split(":", 1)[1].split()[0].strip()
                        break
        else:
            set_step("client", "skip", "Register OIDC client  (skipped)")

        # 7 — issue client cert  (tls_client_auth only)
        if cfg.client_id and method == "tls_client_auth" and ca_cert:

            def do_cert():
                try:
                    paths = issue_client_cert(
                        cfg.client_id,
                        ca_cert,
                        cfg.ca_key_path,
                        cfg.client_cert_output_dir,
                    )
                    cfg.generated_files += list(paths.values())
                    return True, "\n".join(f"  {k}: {v}" for k, v in paths.items())
                except Exception as exc:
                    return False, str(exc)

            if not run("cert", "Issue client certificate", do_cert):
                return
        else:
            set_step("cert", "skip", "Issue client certificate  (skipped)")

        # Final — activate systemd user service (non-blocking)
        _activate_label = "Enable systemd service"
        if cfg.enable_systemd:
            set_step("systemd_activate", "running", _activate_label)
            ok, msg = _try_activate_systemd()
            if ok:
                set_step("systemd_activate", "ok", _activate_label)
                log(f"  {msg}")
            else:
                set_step("systemd_activate", "warn", f"{_activate_label}  (manual steps needed)")
                log(f"[yellow]  systemd activation failed: {msg}[/]")
                log("  Run manually:")
                log("    systemctl --user daemon-reload")
                log("    systemctl --user enable --now x2fa.service")
                log("    loginctl enable-linger  # for auto-start on boot")
        else:
            set_step("systemd_activate", "skip", f"{_activate_label}  (disabled)")

        self.app.call_from_thread(self._on_done)

    # ── Button ────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "copy":
                text = "\n".join(self._plain_lines)
                if _copy_to_clipboard(text):
                    self.notify("Log copied to clipboard.")
                else:
                    self.app.push_screen(_LogOverlay(text))
            case "back":
                self.app.pop_screen()
            case "retry":
                self._reset_and_retry()
            case "abort":
                self.app.exit()

    def _reset_and_retry(self) -> None:
        # Reset step icons to pending
        for step_id, label in _STEPS:
            self.query_one(f"#step-{step_id}", Static).update(
                f"  {_ICONS['pending']}  {label}"
            )
        # Clear log
        self._log.clear()
        self._plain_lines = []
        # Reset buttons
        self.query_one("#retry", Button).disabled = True
        self.query_one("#abort", Button).label = "Abort"
        # Re-run
        self._run_installation()


# ── systemd activation helper ────────────────────────────────────────────────

def _try_activate_systemd() -> tuple[bool, str]:
    """Attempt systemctl --user daemon-reload + enable --now x2fa.service.

    Returns (success, message).  Never raises.
    """
    try:
        r = subprocess.run(
            ["systemctl", "--user", "daemon-reload"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return False, (r.stderr.strip() or "daemon-reload failed")

        r2 = subprocess.run(
            ["systemctl", "--user", "enable", "--now", "x2fa.service"],
            capture_output=True, text=True, timeout=10,
        )
        if r2.returncode != 0:
            return False, (r2.stderr.strip() or "enable --now failed")

        return True, "x2fa.service enabled and started"
    except FileNotFoundError:
        return False, "systemctl not found"
    except subprocess.TimeoutExpired:
        return False, "systemctl timed out"
    except Exception as exc:
        return False, str(exc)


# ── Clipboard helper ──────────────────────────────────────────────────────────

def _copy_to_clipboard(text: str) -> bool:
    """Try system clipboard tools, then Textual's OSC 52. Return True on success."""
    _TOOLS = [
        ["wl-copy"],                           # Wayland
        ["xclip", "-selection", "clipboard"],  # X11
        ["xsel", "--clipboard", "--input"],    # X11 alternative
    ]
    for cmd in _TOOLS:
        try:
            subprocess.run(cmd, input=text, text=True,
                           capture_output=True, timeout=2)
            return True
        except (FileNotFoundError, subprocess.TimeoutExpired):
            continue
    return False


# ── Fallback overlay ──────────────────────────────────────────────────────────

class _LogOverlay(ModalScreen):
    """Full-screen read-only overlay showing the log when clipboard is unavailable."""

    CSS = """
    _LogOverlay {
        align: center middle;
    }
    #overlay_panel {
        width: 90%;
        height: 80%;
        border: round $accent;
        padding: 1 2;
        background: $surface;
    }
    #overlay_panel Static {
        color: $text-muted;
        margin-bottom: 1;
    }
    TextArea {
        height: 1fr;
    }
    """

    def __init__(self, text: str) -> None:
        super().__init__()
        self._text = text

    def compose(self) -> ComposeResult:
        with Container(id="overlay_panel"):
            yield Static(
                "Clipboard not available — select and copy manually  (Esc to close)",
                markup=False,
            )
            yield TextArea(self._text, read_only=True, id="log_text")

    def on_key(self, event) -> None:
        if event.key == "escape":
            self.dismiss()
