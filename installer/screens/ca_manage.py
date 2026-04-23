"""CA management screen — list, add, renew, and revoke trusted CAs."""
import secrets
from pathlib import Path

from textual import work
from textual.app import ComposeResult
from textual.containers import Container, VerticalScroll
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Log, Static

# ── Modes ─────────────────────────────────────────────────────────────────────
_MODE_LIST   = "list"
_MODE_ADD    = "add"
_MODE_RENEW  = "renew"
_MODE_REVOKE = "revoke"


class CAManageScreen(Screen):
    """Post-install CA management: list, add, renew, revoke."""

    CSS = """
    #ca_list {
        height: auto;
        max-height: 12;
        border: solid $panel-lighten-2;
        padding: 0 1;
        margin: 1 0;
        overflow-y: auto;
    }
    #action_form {
        border: solid $accent 30%;
        padding: 1 1;
        margin-top: 1;
        height: auto;
    }
    #action_log {
        height: 8;
        border: solid $panel-lighten-2;
        margin-top: 1;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self._mode = _MODE_LIST
        self._selected_ca: str | None = None

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="panel"):
            yield Static("CA Management", classes="screen-title")

            # ── CA list ────────────────────────────────────────────────────
            yield Static("Registered Certificate Authorities:", classes="field-label")
            with VerticalScroll(id="ca_list"):
                yield Static("[dim]Loading…[/]", id="ca_list_content", markup=True)

            # ── Action buttons ─────────────────────────────────────────────
            with Container(id="action_buttons"):
                yield Button("+ Add CA",    id="btn_add",    variant="default")
                yield Button("↻ Renew CA",  id="btn_renew",  variant="default")
                yield Button("✕ Revoke CA", id="btn_revoke", variant="warning")

            # ── Action form (hidden until an action is chosen) ─────────────
            with Container(id="action_form", classes="hidden"):
                yield Static("", id="form_title", classes="field-label")

                # Fields shared by Add and Renew
                yield Static("CA name:", id="lbl_name", classes="field-label")
                yield Input(placeholder="x2fa-internal-ca", id="f_name")

                # Add-only: import path
                yield Static("Certificate path (PEM):", id="lbl_cert", classes="field-label hidden")
                yield Input(placeholder="/path/to/ca_cert.pem", id="f_cert", classes="hidden")

                # Renew-only: old CA name + new cert generation
                yield Static("Old CA name (to revoke):", id="lbl_old", classes="field-label hidden")
                yield Input(placeholder="x2fa-ca-2024", id="f_old_name", classes="hidden")
                yield Static("New CN:", id="lbl_cn", classes="field-label hidden")
                yield Input(placeholder="X2FA Internal CA", id="f_cn", classes="hidden")
                yield Static("Validity (days):", id="lbl_days", classes="field-label hidden")
                yield Input(value="3650", placeholder="3650", id="f_days", classes="hidden")
                yield Static("New key output path:", id="lbl_key", classes="field-label hidden")
                yield Input(placeholder="/etc/x2fa/ca_key_new.pem", id="f_key", classes="hidden")
                yield Static("New cert output path:", id="lbl_new_cert", classes="field-label hidden")
                yield Input(placeholder="/etc/x2fa/ca_cert_new.pem", id="f_new_cert", classes="hidden")

                # Revoke-only: CA name (uses f_name)

                with Container(id="form_buttons"):
                    yield Button("Cancel", id="btn_cancel", variant="default")
                    yield Button("Execute", id="btn_execute", variant="primary")

            # ── Action log ─────────────────────────────────────────────────
            yield Log(id="action_log", auto_scroll=True, highlight=True)

            with Container(id="buttons"):
                yield Button("← Back", id="back")
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_ca_list()

    # ── CA list refresh ────────────────────────────────────────────────────

    @work(thread=True)
    def _refresh_ca_list(self) -> None:
        from installer.runner import list_cas
        install_root = self.app.config.install_root
        config_root = self.app.config.x2fa_home
        ok, output = list_cas(install_root, config_root)
        self.call_from_thread(self._update_ca_list, ok, output)

    def _update_ca_list(self, ok: bool, output: str) -> None:
        content = self.query_one("#ca_list_content", Static)
        if not ok or not output.strip():
            content.update("[dim]No CAs registered yet.[/]")
        else:
            content.update(output)

    # ── Mode switching ─────────────────────────────────────────────────────

    def _show_form(self, mode: str) -> None:
        self._mode = mode
        form = self.query_one("#action_form")
        form.remove_class("hidden")

        # Hide all optional fields first
        optional = [
            "#lbl_cert", "#f_cert",
            "#lbl_old", "#f_old_name",
            "#lbl_cn", "#f_cn",
            "#lbl_days", "#f_days",
            "#lbl_key", "#f_key",
            "#lbl_new_cert", "#f_new_cert",
        ]
        for wid in optional:
            self.query_one(wid).add_class("hidden")

        title = self.query_one("#form_title", Static)
        if mode == _MODE_ADD:
            title.update("Add CA  —  enter name and path to PEM certificate")
            for wid in ("#lbl_cert", "#f_cert"):
                self.query_one(wid).remove_class("hidden")
            self.query_one("#f_name").placeholder = "x2fa-internal-ca"

        elif mode == _MODE_RENEW:
            title.update("Renew CA  —  generate new cert, register it, revoke old")
            for wid in ("#lbl_old", "#f_old_name",
                        "#lbl_cn", "#f_cn",
                        "#lbl_days", "#f_days",
                        "#lbl_key", "#f_key",
                        "#lbl_new_cert", "#f_new_cert"):
                self.query_one(wid).remove_class("hidden")
            self.query_one("#f_name").placeholder = "x2fa-ca-2026  (new name)"

        elif mode == _MODE_REVOKE:
            title.update("Revoke CA  —  enter name of the CA to deactivate")
            self.query_one("#f_name").placeholder = "x2fa-internal-ca"

    def _hide_form(self) -> None:
        self.query_one("#action_form").add_class("hidden")
        self._mode = _MODE_LIST

    # ── Execute action ─────────────────────────────────────────────────────

    @work(thread=True)
    def _execute_add(self, name: str, cert_path: str) -> None:
        from installer.runner import add_ca
        log = self.query_one("#action_log", Log)
        install_root = self.app.config.install_root
        config_root = self.app.config.x2fa_home

        self.call_from_thread(log.write_line, f"Registering CA '{name}' from {cert_path} …")
        ok, output = add_ca(name, cert_path, install_root, config_root)
        for line in output.splitlines():
            self.call_from_thread(log.write_line, f"  {line}")
        if ok:
            self.call_from_thread(log.write_line, "[green]✓  CA registered.[/]")
            self.call_from_thread(self._hide_form)
            self.call_from_thread(self._refresh_ca_list)
        else:
            self.call_from_thread(log.write_line, "[red]✗  Failed.[/]")

    @work(thread=True)
    def _execute_renew(
        self, old_name: str, new_name: str, cn: str,
        validity_days: int, key_path: str, cert_path: str,
    ) -> None:
        from installer.ca import generate_ca
        from installer.runner import add_ca, revoke_ca
        log = self.query_one("#action_log", Log)
        install_root = self.app.config.install_root
        config_root = self.app.config.x2fa_home

        self.call_from_thread(log.write_line, f"Generating new CA certificate …")
        try:
            generate_ca(cn, validity_days, key_path, cert_path)
            self.call_from_thread(log.write_line, f"  Key:  {key_path}  (mode 0600)")
            self.call_from_thread(log.write_line, f"  Cert: {cert_path}")
        except Exception as exc:
            self.call_from_thread(log.write_line, f"[red]✗  CA generation failed: {exc}[/]")
            return

        self.call_from_thread(log.write_line, f"Registering new CA '{new_name}' …")
        ok, output = add_ca(new_name, cert_path, install_root, config_root)
        for line in output.splitlines():
            self.call_from_thread(log.write_line, f"  {line}")
        if not ok:
            self.call_from_thread(log.write_line, "[red]✗  Registration failed.[/]")
            return
        self.call_from_thread(log.write_line, "[green]✓  New CA registered.[/]")

        self.call_from_thread(log.write_line, f"Revoking old CA '{old_name}' …")
        ok, output = revoke_ca(old_name, install_root, config_root)
        for line in output.splitlines():
            self.call_from_thread(log.write_line, f"  {line}")
        status = "[green]✓  Revoked.[/]" if ok else "[yellow]⚠  Revoke failed (check name).[/]"
        self.call_from_thread(log.write_line, status)

        self.call_from_thread(log.write_line,
            "\n[dim]Re-issue client certs with: "
            f"flask issue-client-cert <client_id> --ca {new_name}[/]")
        self.call_from_thread(self._hide_form)
        self.call_from_thread(self._refresh_ca_list)

    @work(thread=True)
    def _execute_revoke(self, name: str) -> None:
        from installer.runner import revoke_ca
        log = self.query_one("#action_log", Log)
        install_root = self.app.config.install_root
        config_root = self.app.config.x2fa_home

        self.call_from_thread(log.write_line, f"Revoking CA '{name}' …")
        ok, output = revoke_ca(name, install_root, config_root)
        for line in output.splitlines():
            self.call_from_thread(log.write_line, f"  {line}")
        status = "[green]✓  Revoked.[/]" if ok else "[red]✗  Failed.[/]"
        self.call_from_thread(log.write_line, status)
        self.call_from_thread(self._hide_form)
        self.call_from_thread(self._refresh_ca_list)

    # ── Events ────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "btn_add":    self._show_form(_MODE_ADD)
            case "btn_renew":  self._show_form(_MODE_RENEW)
            case "btn_revoke": self._show_form(_MODE_REVOKE)
            case "btn_cancel": self._hide_form()
            case "back":       self.app.pop_screen()
            case "btn_execute":
                self._dispatch_execute()

    def _dispatch_execute(self) -> None:
        mode = self._mode
        f_name     = self.query_one("#f_name",     Input).value.strip()
        f_cert     = self.query_one("#f_cert",     Input).value.strip()
        f_old_name = self.query_one("#f_old_name", Input).value.strip()
        f_cn       = self.query_one("#f_cn",       Input).value.strip()
        f_days     = self.query_one("#f_days",     Input).value.strip()
        f_key      = self.query_one("#f_key",      Input).value.strip()
        f_new_cert = self.query_one("#f_new_cert", Input).value.strip()

        if mode == _MODE_ADD:
            if not f_name or not f_cert:
                self.notify("CA name and certificate path are required.", severity="error")
                return
            self._execute_add(f_name, f_cert)

        elif mode == _MODE_RENEW:
            if not all([f_old_name, f_name, f_cn, f_days, f_key, f_new_cert]):
                self.notify("All fields are required for renewal.", severity="error")
                return
            try:
                days = int(f_days)
            except ValueError:
                self.notify("Validity must be a number.", severity="error")
                return
            self._execute_renew(f_old_name, f_name, f_cn, days, f_key, f_new_cert)

        elif mode == _MODE_REVOKE:
            if not f_name:
                self.notify("CA name is required.", severity="error")
                return
            self._execute_revoke(f_name)
