"""Preflight checks screen."""

import os
import shutil
import socket
import sys
from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Collapsible, Footer, Header, Markdown, Static

_HELP_TEXT = """\
## Preflight Checks

This installer configures X2FA itself — secrets, database connection, domain,
OIDC clients, and certificates. **System-level setup is the admin's responsibility
and must be completed before running this installer.**

### Prerequisites (admin's responsibility)

Before running the installer, ensure the following are already in place:

- **Dedicated system user** — X2FA should run as an unprivileged user (e.g. `x2fa`).
  Create it with: `sudo useradd --system --shell /sbin/nologin --create-home --home-dir /var/lib/x2fa x2fa`
  Then run this installer as that user: `sudo -u x2fa uv run installer`
- **Reverse proxy** — nginx, Caddy, or similar must be installed and configured to
  forward requests to `127.0.0.1:5000`. The Summary screen provides a ready-to-use
  config snippet.
- **Database server** — required only for PostgreSQL or MySQL backends. SQLite (the
  default) needs no preparation.

### Check types

**Blocking** (red ✗): The installer cannot continue until this is fixed.
The Continue button is hidden when any blocking check fails.

**Warning** (yellow ⚠): Installation can proceed, but the condition may cause
problems at runtime. Review the hint and decide whether to fix it first.

### Checks performed

| Check | Type | What to do if it fails |
|---|---|---|
| Python ≥ 3.11 | Blocking | Upgrade Python. `uv python install 3.11` works. |
| uv package manager | Blocking | Install uv: `curl -LsSf https://astral.sh/uv/install.sh | sh` |
| Config dir writable | Blocking | `mkdir -p ~/.config/x2fa && chmod u+rwx ~/.config/x2fa` |
| Data dir writable | Blocking | `mkdir -p ~/.local/share/x2fa && chmod u+rwx ~/.local/share/x2fa` |
| systemd user dir writable | Blocking | `mkdir -p ~/.config/systemd/user && chmod u+rwx ~/.config/systemd/user` |
| Running as root | Warning | Create a dedicated user and re-run as that user (see Prerequisites above) |
| Port 5000 free | Warning | Stop the conflicting service: `lsof -ti:5000 | xargs kill` |
| Redis reachable | Warning | Optional — only required when running multiple Gunicorn workers |
"""


def _check_dir(path: Path) -> tuple[bool, str]:
    """Return (ok, hint) for a directory that the installer must be able to write to."""
    if path.exists():
        if os.access(path, os.W_OK):
            return True, ""
        return False, f"chmod u+rwx {path}"
    # Directory doesn't exist yet — walk up to find the first existing ancestor.
    ancestor = path.parent
    while not ancestor.exists() and ancestor != ancestor.parent:
        ancestor = ancestor.parent
    if os.access(ancestor, os.W_OK):
        return True, ""   # mkdir -p will succeed
    return False, f"chmod u+rwx {ancestor}  (will be created under it)"


def _run_checks(config_root: Path | None = None) -> list[dict]:
    checks = []
    root = config_root if config_root is not None else Path.home()
    home = Path.home()

    def _fmt(p: Path) -> str:
        """Display path with ~ substitution for readability."""
        try:
            return "~/" + str(p.relative_to(home))
        except ValueError:
            return str(p)

    # Root check (warning only — the installer can proceed, but it is unusual)
    import pwd
    is_root = os.geteuid() == 0
    try:
        username = pwd.getpwuid(os.geteuid()).pw_name
    except KeyError:
        username = str(os.geteuid())
    entry: dict = {
        "label": "Running as root" if is_root else f"Running as {username}",
        "ok": not is_root,
        "blocking": False,
    }
    if is_root:
        entry["hint"] = (
            "X2FA should not run as root. "
            "Create a dedicated user and re-run: sudo -u x2fa uv run installer"
        )
    checks.append(entry)

    # Python version
    ok = sys.version_info >= (3, 11)
    checks.append(
        {
            "label": f"Python ≥ 3.11  (found {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro})",
            "ok": ok,
            "blocking": True,
            "hint": "Upgrade Python or run: uv python install 3.11",
        }
    )

    # uv
    ok = shutil.which("uv") is not None
    checks.append(
        {
            "label": "uv package manager",
            "ok": ok,
            "blocking": True,
            "hint": "Install uv: curl -LsSf https://astral.sh/uv/install.sh | sh",
        }
    )

    # XDG directories
    _dirs = [
        (root / ".config" / "x2fa",         "Config dir"),
        (root / ".local" / "share" / "x2fa", "Data dir"),
        (root / ".config" / "systemd" / "user", "systemd user dir"),
    ]
    for path, label in _dirs:
        ok, fix = _check_dir(path)
        entry: dict = {
            "label": f"{label}  {_fmt(path)}",
            "ok": ok,
            "blocking": True,
        }
        if not ok:
            entry["hint"] = f"mkdir -p {path} && {fix}"
        checks.append(entry)

    # Port 5000
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(("127.0.0.1", 5000))
        s.close()
        port_ok = True
    except OSError:
        port_ok = False
    entry: dict = {
        "label": "Port 5000 free" if port_ok else "Port 5000 occupied",
        "ok": port_ok,
        "blocking": False,
    }
    if not port_ok:
        entry["hint"] = "Stop the process using this port: lsof -ti:5000 | xargs kill"
    checks.append(entry)

    # Redis (warn only)
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1)
        s.connect(("127.0.0.1", 6379))
        s.close()
        redis_ok = True
    except Exception:
        redis_ok = False
    entry = {
        "label": "Redis reachable on localhost:6379" if redis_ok else "Redis not reachable on localhost:6379",
        "ok": redis_ok,
        "blocking": False,
    }
    if not redis_ok:
        entry["hint"] = "Optional — only required for multiple Gunicorn workers; memory:// is used otherwise"
    checks.append(entry)

    return checks


class WelcomeScreen(Screen):
    BINDINGS = [("f1", "toggle_help", "Help")]

    def action_toggle_help(self) -> None:
        self.query_one("#help_panel", Collapsible).collapsed ^= True

    def compose(self) -> ComposeResult:
        checks = _run_checks(self.app.config.config_root)
        blocking_failed = any(not c["ok"] and c["blocking"] for c in checks)

        yield Header()
        with Container(id="panel"):
            yield Static("Preflight Checks", classes="screen-title")
            with Collapsible(title="Help  (F1)", id="help_panel", collapsed=True):
                yield Markdown(_HELP_TEXT)

            for c in checks:
                if c["ok"]:
                    mark = "[green]✓[/]"
                elif c["blocking"]:
                    mark = "[red]✗[/]"
                else:
                    mark = "[yellow]⚠[/]"
                # hints: shown only on failure; info: shown only on success
                note = ""
                if not c["ok"] and c.get("hint"):
                    note = f"\n    [dim]{c['hint']}[/]"
                elif c["ok"] and c.get("info"):
                    note = f"\n    [dim]{c['info']}[/]"
                yield Static(f"  {mark}  {c['label']}{note}", markup=True)

            if blocking_failed:
                yield Static(
                    "\n[red bold]Fix the errors above before continuing.[/]",
                    markup=True,
                )

            with Container(id="buttons"):
                yield Button("← Back", id="back")
                if not blocking_failed:
                    yield Button("Continue →", id="next", variant="success")
        yield Footer()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "back":
                self.app.pop_screen()
            case "next":
                from installer.screens.database import DatabaseScreen
                self.app.push_screen(DatabaseScreen())
