"""Execute screen — runs all install steps sequentially with live progress output."""

from textual import work
from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Log, Static

_PKI_CA_METHODS = {"tls_client_auth", "private_key_jwt"}

_STEPS = [
    ("config", "Write configuration files"),
    ("initdb", "Initialize database"),
    ("initkeys", "Generate signing keys"),
    ("ca", "Set up Certificate Authority"),
    ("add_ca", "Register CA in X2FA"),
    ("client", "Register OIDC client"),
    ("cert", "Issue client certificate"),
]

_ICONS = {
    "pending": "[dim]○[/]",
    "running": "[yellow]▶[/]",
    "ok": "[green]✓[/]",
    "error": "[red]✗[/]",
    "skip": "[dim]–[/]",
}


class ExecuteScreen(Screen):
    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="panel"):
            yield Static("Installing X2FA", classes="screen-title")
            with Container(id="steps"):
                for step_id, label in _STEPS:
                    yield Static(
                        f"  {_ICONS['pending']}  {label}",
                        id=f"step-{step_id}",
                        markup=True,
                    )
            yield Log(id="log", auto_scroll=True, highlight=True)
            with Container(id="buttons"):
                yield Button("Abort", id="abort", variant="error")
        yield Footer()

    def on_mount(self) -> None:
        self._log = self.query_one("#log", Log)
        self._run_installation()

    # ── UI helpers (must be called on the main thread) ────────────────────

    def _set_step(self, step_id: str, status: str, label: str) -> None:
        self.query_one(f"#step-{step_id}", Static).update(
            f"  {_ICONS[status]}  {label}"
        )

    def _write(self, line: str) -> None:
        self._log.write_line(line)

    def _on_done(self) -> None:
        from .summary import SummaryScreen

        self.app.push_screen(SummaryScreen())

    def _on_error(self, step_id: str, label: str, message: str) -> None:
        self._write(f"\n[red bold]Failed:[/] {label}")
        self._write(f"[red]{message}[/]")
        self.query_one("#abort", Button).label = "Quit"

    # ── Background worker ─────────────────────────────────────────────────

    @work(thread=True)
    def _run_installation(self) -> None:
        from ..ca import generate_ca, issue_client_cert
        from ..config_writer import write_configs
        from ..runner import add_ca, add_client, init_db, init_keys

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

        # 2 — init-db
        if not run("initdb", "Initialize database", lambda: init_db(cfg.install_root)):
            return

        # 3 — init-keys
        if not run(
            "initkeys", "Generate signing keys", lambda: init_keys(cfg.install_root)
        ):
            return

        # 4 — CA  (PKI methods only)
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

            if not run("client", "Register OIDC client", do_client):
                return
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

        self.app.call_from_thread(self._on_done)

    # ── Button ────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "abort":
            self.app.exit()
