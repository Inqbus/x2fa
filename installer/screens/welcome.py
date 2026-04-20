"""Preflight checks screen."""

import os
import shutil
import socket
import sys

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Collapsible, Footer, Header, Markdown, Static

_HELP_TEXT = """\
## Preflight Checks

These checks run automatically before the installer proceeds.

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
| Running as root/user | Info | No action needed — informational only |
| Port 5000 free | Warning | Stop the conflicting service: `lsof -ti:5000 | xargs kill` |
| Redis reachable | Warning | Optional — only required when running multiple Gunicorn workers |
"""


def _run_checks() -> list[dict]:
    checks = []
    is_root = os.geteuid() == 0
    checks.append(
        {
            "label": f"Running as {'root' if is_root else 'non-root user'}",
            "ok": True,
            "blocking": False,
            # Informational note — only relevant for non-root users
            "info": "Use --config-root or run as root for system-wide /etc/x2fa paths" if not is_root else None,
        }
    )

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
        checks = _run_checks()
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
