"""User setup screen — create or select the unprivileged system user for X2FA."""

import grp
import os
import pwd
import subprocess
import sys

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Footer, Header, Input, Static


def _existing_unprivileged_users() -> list[str]:
    """Return non-system, non-root usernames as candidates (uid >= 1000)."""
    return sorted(
        e.pw_name for e in pwd.getpwall()
        if e.pw_uid >= 1000 and e.pw_name not in ("nobody",)
    )


def _user_exists(name: str) -> bool:
    try:
        pwd.getpwnam(name)
        return True
    except KeyError:
        return False


class UserSetupScreen(Screen):
    """Create a dedicated system account for X2FA, then display the re-run command."""

    _is_root: bool = os.geteuid() == 0

    def compose(self) -> ComposeResult:
        yield Header()
        with Container(id="panel"):
            yield Static("Create X2FA System User", classes="screen-title")
            yield Static(
                "[dim]X2FA must run as a dedicated unprivileged system user.\n"
                "This screen creates that user and shows the command to re-run\n"
                "the installer under the new account.[/]",
                markup=True, classes="hint",
            )

            yield Static("Username [bold red]*[/]:", markup=True, classes="field-label")
            yield Input(value="x2fa", id="username")
            yield Static(
                "[dim]Default: x2fa — change only if you prefer a different name.[/]",
                markup=True, classes="hint",
            )

            if not self._is_root:
                yield Static(
                    "sudo password [bold red]*[/]:", markup=True, classes="field-label"
                )
                yield Input(
                    placeholder="Enter your sudo password",
                    password=True,
                    id="sudo_password",
                )
                yield Static(
                    "[dim]Required to run `sudo useradd`. "
                    "The password is used once and never stored.[/]",
                    markup=True, classes="hint",
                )
            else:
                yield Static(
                    "[dim]Running as root — no password required.[/]",
                    markup=True, classes="hint",
                )

            yield Static("", id="status", markup=True, classes="hint")

            with Container(id="buttons"):
                yield Button("← Back", id="back")
                yield Button("Create User", id="create", variant="primary")
        yield Footer()

    # ── Events ────────────────────────────────────────────────────────────

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "back":
                self.app.pop_screen()
            case "create":
                self._do_create()

    # ── Logic ─────────────────────────────────────────────────────────────

    def _do_create(self) -> None:
        username = self.query_one("#username", Input).value.strip()
        if not username:
            self.notify("Username is required.", severity="error")
            return

        status = self.query_one("#status", Static)

        if _user_exists(username):
            status.update(
                f"[yellow]User '{username}' already exists.[/]\n\n"
                + _rerun_hint(username)
            )
            return

        if self._is_root:
            ok, msg = _create_user_as_root(username)
        else:
            password = self.query_one("#sudo_password", Input).value
            if not password:
                self.notify("sudo password is required.", severity="error")
                return
            ok, msg = _create_user_with_sudo(username, password)

        if ok:
            status.update(
                f"[green]✓ User '{username}' created.[/]\n\n"
                + _rerun_hint(username)
            )
            self.query_one("#create", Button).disabled = True
        else:
            status.update(f"[red]✗ Failed:[/] {msg}")
            self.notify("User creation failed — see details above.", severity="error")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _create_user_as_root(username: str) -> tuple[bool, str]:
    """Run useradd directly (caller is root)."""
    try:
        subprocess.run(
            ["useradd", "--system", "--shell", "/sbin/nologin",
             "--create-home", "--home-dir", f"/var/lib/{username}", username],
            check=True,
            capture_output=True,
            text=True,
        )
        return True, ""
    except subprocess.CalledProcessError as exc:
        return False, (exc.stderr or exc.stdout or str(exc)).strip()
    except FileNotFoundError:
        return False, "`useradd` not found — install shadow-utils or adduser."


def _create_user_with_sudo(username: str, password: str) -> tuple[bool, str]:
    """Run useradd via sudo -S (password piped to stdin)."""
    try:
        result = subprocess.run(
            ["sudo", "--stdin", "useradd",
             "--system", "--shell", "/sbin/nologin",
             "--create-home", "--home-dir", f"/var/lib/{username}", username],
            input=password + "\n",
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return True, ""
        return False, (result.stderr or result.stdout or "unknown error").strip()
    except FileNotFoundError:
        return False, "`sudo` or `useradd` not found."


def _rerun_hint(username: str) -> str:
    """Return the markup string telling the admin how to re-run the installer."""
    args = " ".join(sys.argv[1:])
    cmd = f"sudo -u {username} uv run installer"
    if args:
        cmd += f" {args}"
    return (
        f"Re-run the installer as [bold]{username}[/]:\n\n"
        f"  [bold cyan]{cmd}[/]\n\n"
        "[dim]After the installer completes, start X2FA the same way:[/]\n"
        f"  [dim]sudo -u {username} ENV_FOR_DYNACONF=production "
        "uv run gunicorn 'x2fa.wsgi:app' --bind 127.0.0.1:5000[/]"
    )
