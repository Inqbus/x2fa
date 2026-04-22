# Proposal: Enhanced Installer Documentation

**Status:** Superseded — see `docs/installer.md` for the current reference  
**Date:** 2026-04-20  

---

## 1. Objective

The installer TUI is feature-complete — it walks through every configuration step and
executes the full setup automatically. However, an operator encountering it for the first
time faces a wall of choice with very little guidance:

- Six authentication methods with no explanation of trade-offs or consequences
- CA setup fields (CN, validity days, key paths) with no indication of what values are
  appropriate or where the files must land for the proxy to find them
- A Security screen that auto-generates secrets — but offers no explanation of what those
  secrets protect or how they relate to the running application
- A `--config-root` flag that is entirely undocumented

The goal of this proposal is to make every choice in the installer self-explaining:
operators should be able to complete the installation without leaving the terminal to
look things up, and should understand *why* they are making each decision, not just
*what* to type.

---

## 2. Gap Analysis

### 2.1 In-TUI gaps

| Screen | Missing documentation |
|---|---|
| WelcomeScreen | No explanation of what a "blocking" vs "warning" check means; no guidance on what to do when a check fails |
| DatabaseScreen | No explanation of SQLite limitations (single writer, no replication); no note that PostgreSQL/MySQL require `uv sync --extra postgres/mysql` |
| DomainScreen | No explanation of the `ORIGIN` value derived from the domain; no guidance on proxy types and their TLS implications |
| SecurityScreen | No explanation of what `SECRET_KEY` and `SECRET_SALT` protect; no note that changing them after install invalidates all sessions and encrypted TOTP secrets; no guidance on when Redis is required |
| ClientScreen | No per-method explanation; no security comparison table; no note that `client_secret_post`/`_basic` transmit secrets on every request; no guidance on which method to choose |
| CASetupScreen | No explanation of CA CN / validity conventions; no note about where key files must be accessible from the reverse proxy; no explanation of import vs generate trade-offs |
| ExecuteScreen | No description of what each step does or what failure means; no guidance on how to recover from a partial failure |
| SummaryScreen | No next-steps checklist ordered by priority; no copy-paste commands for the systemd unit |

### 2.2 Workflow gaps

The following complete workflows are not documented anywhere:

1. **`--config-root` usage** — what it is for, when to use it, and how it interacts
   with the XDG paths for configs and data
2. **Multi-instance deployment** — running two X2FA instances (e.g. staging + production)
   on the same host using distinct config roots
3. **Reconfiguration after install** — what to re-run (or not re-run) to change a domain,
   add a CA, or rotate credentials without re-executing the full install
4. **Headless / automated install** — there is no `--non-interactive` mode; operators
   setting up X2FA via Ansible or CI have no supported path
5. **Upgrade workflow** — `flask db-upgrade` (Alembic) vs `flask init-db`; when to use
   each; what is safe to run on a live database
6. **CA Manage workflow** — what the "Manage CAs" main-menu option does, when to use it,
   and how it interacts with existing clients
7. **Reverse proxy integration details per proxy type** — the current summary screen
   shows one static snippet; there is no guidance on mTLS proxy config for
   `tls_client_auth` vs the simpler config for secret-based methods

### 2.3 Missing reference page

`INSTALL.md` covers the happy path but:
- Still references `src/x2fa/config_files/` as the config location (pre-`config_root`
  design; actual location is `~/.config/x2fa/`)
- States that `init-db` is "destructive" without mentioning `db-upgrade`
- Provides no comparison between auth methods beyond a table
- Does not cover `--config-root`

---

## 3. Method

Documentation improvements will be delivered at three levels:

### Level 1 — In-TUI contextual help panels

Each screen gains a collapsible help panel triggered by the `F1` key (or a visible
`[?] Help` button). The panel renders a short `Markdown`-formatted section explaining:

- What this screen configures
- The recommended choice for common scenarios
- Consequences of each option
- A link to the relevant section in the external documentation

The panel is implemented as a `Markdown` widget inside a `Collapsible` container
(both available in Textual 8.x). It renders inline without leaving the screen.

Example for the ClientScreen auth method panel:

```
┌─ Help: Authentication method ──────────────────────────────────────────┐
│                                                                         │
│  tls_client_auth (recommended)                                          │
│    The installer generates a CA + client certificate. The relying       │
│    party presents the certificate at /token; the reverse proxy          │
│    verifies it against the CA and forwards it in X-Client-Certificate.  │
│    No secret is ever transmitted.                                       │
│                                                                         │
│  client_secret_post / client_secret_basic                               │
│    A shared 64-char secret is auto-generated and printed once.          │
│    The relying party sends it on every request. Only acceptable          │
│    behind TLS. Not recommended for production.                          │
│                                                                         │
│  See: https://… / docs/trust_options.md                                 │
└─────────────────────────────────────────────────────────────────────────┘
```

### Level 2 — Dynamic field hints

Replace the static placeholder-level hint `Static` widgets below each field with
reactive hints that update based on the current input value. Examples:

- **Domain field**: as the operator types, show `ORIGIN will be: https://…`
- **CA validity field**: below the number, show a human-readable duration
  (`3650 days ≈ 10 years`) and a warning if the value is below 365 days
- **CA key path / cert path**: show whether the parent directory exists and is writable
- **Redis URI field**: show a connection-test indicator (green ✓ / red ✗) next to the
  field, triggered on focus-out via a background worker

### Level 3 — Configuration Review screen

Insert a **Review** screen between the last input screen (CASetupScreen or ClientScreen)
and ExecuteScreen. The Review screen renders a read-only summary of all collected
configuration values, grouped by topic, with each value displayed alongside its key name
and a brief description. This gives the operator one last chance to catch mistakes before
the irreversible execute step.

```
┌─ Review: Configuration Summary ────────────────────────────────────────────┐
│                                                                             │
│  DATABASE                                                                   │
│    Type:  SQLite                                                            │
│    Path:  /home/x2fa/.local/share/x2fa/db.sqlite                           │
│                                                                             │
│  DOMAIN                                                                     │
│    Domain:  2fa.myapp.io                                                    │
│    Origin:  https://2fa.myapp.io                                            │
│    Proxy:   Caddy                                                           │
│                                                                             │
│  SECURITY                                                                   │
│    SECRET_KEY:  dead…cafe  (64 hex chars)                                   │
│    SECRET_SALT: beef…1234  (32 hex chars)                                   │
│    Rate limiter: memory://  (single worker)                                 │
│                                                                             │
│  CLIENT                                                                     │
│    Client ID:    shop.example.com                                           │
│    Redirect URI: https://shop.example.com/callback                          │
│    Auth method:  tls_client_auth                                            │
│                                                                             │
│  CERTIFICATE AUTHORITY                                                      │
│    Action:   Generate new CA                                                │
│    CN:       X2FA Internal CA                                               │
│    Validity: 3650 days (≈ 10 years)                                         │
│    Key:      /home/x2fa/.local/share/x2fa/ca_key.pem                       │
│    Cert:     /home/x2fa/.local/share/x2fa/ca_cert.pem                      │
│                                                                             │
│              [← Back]  [Confirm & Install →]                                │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Implementation Details

### 4.1 In-TUI help panels

**File:** `installer/screens/*.py`  
**New dependency:** None. `Collapsible` and `Markdown` are in Textual 8.x stdlib.

Each screen gets:

```python
from textual.widgets import Collapsible, Markdown

# In compose():
with Collapsible(title="Help  (F1)", id="help_panel", collapsed=True):
    yield Markdown(HELP_TEXT)

# Keybinding:
BINDINGS = [("f1", "toggle_help", "Help")]

def action_toggle_help(self) -> None:
    self.query_one("#help_panel", Collapsible).collapsed ^= True
```

Help text constants are defined per-screen in the same file, as module-level
`HELP_TEXT` strings written in Markdown. This keeps the content co-located with the
screen it describes and makes future updates straightforward.

**Help text to write for each screen:**

| Screen | Topics to cover |
|---|---|
| WelcomeScreen | What each check means; what to do when blocking checks fail; what "blocking" vs "warning" means |
| DatabaseScreen | SQLite: single-process only, no replication, suitable for < ~10k users; PostgreSQL/MySQL: require extra package; connection URI format |
| DomainScreen | How ORIGIN is derived; proxy types and their TLS approach; note that `traefik` and `other` require manual TLS configuration |
| SecurityScreen | What SECRET_KEY protects (sessions, encrypted TOTP secrets, signing keys); what SECRET_SALT protects (IP anonymisation in audit log); why Redis is required for multiple Gunicorn workers |
| ClientScreen | Full comparison of all 6 auth methods with trust model, complexity, and production suitability; what happens after this screen for each method |
| CASetupScreen | CA CN conventions (e.g. "myapp Internal CA" not a hostname); validity trade-offs (longer = less maintenance, shorter = better rotation hygiene); where the key file must be readable for the reverse proxy; import vs generate — when to import (existing enterprise CA, HSM-stored CA) |
| ExecuteScreen | What each step does; how to recover from failures (which steps are idempotent, which are not) |
| SummaryScreen | Ordered next-steps checklist (1. configure proxy, 2. start X2FA, 3. configure relying party, 4. test the flow) |

### 4.2 Dynamic field hints

**Files:** `installer/screens/domain.py`, `ca_setup.py`, `security.py`

Implement reactive hint updates in the `on_input_changed` handlers already present in
each screen. Replace static `Static` widgets with reactive ones:

```python
# domain.py — show derived ORIGIN as the user types
def on_input_changed(self, event: Input.Changed) -> None:
    if event.input.id == "domain":
        val = event.value.strip()
        self.app.configure.domain = val
        origin = f"https://{val}" if val else ""
        self.query_one("#origin_hint", Static).update(
            f"[dim]ORIGIN will be: {origin}[/]" if origin else "[dim]Enter a domain name.[/]"
        )


# ca_setup.py — human-readable validity duration
def on_input_changed(self, event: Input.Changed) -> None:
    if event.input.id == "ca_validity_days":
        try:
            days = int(event.value)
            years = days / 365
            warn = "  [yellow]⚠ Short validity — consider ≥ 365 days[/]" if days < 365 else ""
            self.query_one("#validity_hint", Static).update(
                f"[dim]≈ {years:.1f} years{warn}[/]"
            )
        except ValueError:
            pass
```

**Redis connectivity check** (SecurityScreen, triggered on focus-out of `#redis_uri`):

```python
@work(thread=True)
def _check_redis(self, uri: str) -> None:
    import redis as redis_lib
    try:
        r = redis_lib.from_url(uri, socket_connect_timeout=2)
        r.ping()
        ok = True
    except Exception:
        ok = False
    self.app.call_from_thread(
        self.query_one("#redis_status", Static).update,
        "[green]✓ reachable[/]" if ok else "[red]✗ unreachable[/]",
    )
```

### 4.3 Configuration Review screen

**New file:** `installer/screens/review.py`

The Review screen reads all values from `app.config` and renders them in grouped
read-only sections using `Static` widgets with markup. No input widgets are present —
it is display-only. Navigation: `← Back` returns to the preceding screen (ClientScreen
or CASetupScreen depending on auth method); `Confirm & Install →` pushes ExecuteScreen.

The screen is inserted in the navigation flow in `ca_setup.py` and `client.py`:

```python
# client.py — for non-PKI methods:
from .review import ReviewScreen
self.app.push_screen(ReviewScreen())

# ca_setup.py — after CASetupScreen validation:
from .review import ReviewScreen
self.app.push_screen(ReviewScreen())
```

The `ReviewScreen.on_button_pressed` handler for `#confirm`:
```python
case "confirm":
    from .execute import ExecuteScreen
    self.app.push_screen(ExecuteScreen())
```

### 4.4 Headless / answer-file mode

**New file:** `installer/answers.py` (dataclass + TOML loader)  
**Modified file:** `installer/__main__.py`

Add a `--answers <file.toml>` flag. When provided, the installer reads all configuration
values from the file, skips all TUI screens, and runs the execute step directly. Output
goes to stdout.

Answer file format mirrors `InstallConfig` fields:

```toml
# x2fa-answers.toml
domain             = "2fa.myapp.io"
db_type            = "sqlite"
proxy_type         = "caddy"
client_id          = "shop.example.com"
client_redirect_uri = "https://shop.example.com/callback"
client_auth_method = "tls_client_auth"
ca_action          = "generate"
ca_name            = "myapp-ca"
ca_cn              = "Myapp Internal CA"
ca_validity_days   = 3650
# SECRET_KEY and SECRET_SALT are auto-generated if omitted
```

Implementation sketch:

```python
# __main__.py
if args.answers:
    from installer.answers import load_answers, run_headless
    cfg = load_answers(args.answers)
    sys.exit(0 if run_headless(cfg) else 1)
else:
    InstallerApp(config_root=args.config_root).run()
```

`run_headless` calls `write_configs`, `init_db`, `init_keys`, etc. directly from
`runner.py` and `ca.py` — no Textual involved.

### 4.5 External documentation pages

**New file:** `docs/installer_reference.md`

A screen-by-screen reference covering every field, its default, its valid range, what
it maps to in the generated config files, and the consequences of common choices.
Structure:

```
1. CLI flags (--config-root, --answers)
2. WelcomeScreen — preflight checks
3. DatabaseScreen — db_type, db_uri
4. DomainScreen — domain, proxy_type
5. SecurityScreen — secret_key, secret_salt, use_redis, redis_uri
6. ClientScreen — client_id, client_redirect_uri, client_auth_method,
                  cert_out_dir, jwks_uri, ss_cert_path
7. CASetupScreen — ca_action, ca_name, ca_cn, ca_validity_days,
                   ca_key_path, ca_cert_path, ca_import_path
8. ExecuteScreen — what each step does, idempotency notes
9. SummaryScreen — next-steps checklist
```

**Updated file:** `INSTALL.md`

- Correct config file path from `src/x2fa/config_files/` to `~/.config/x2fa/`
- Add `--config-root` section with multi-instance example
- Replace "init-db is destructive" with `flask init-db` vs `flask db-upgrade` guidance
- Add ordered next-steps checklist at the top
- Add recovery section for failed execute step

---

## 5. Prioritisation

| Priority | Work item | Effort | Value |
|---|---|---|---|
| 1 | Help panels (F1) for ClientScreen and CASetupScreen | M | Very high — most decision-heavy screens |
| 2 | Configuration Review screen | M | High — prevents hard-to-reverse mistakes |
| 3 | Dynamic hints (ORIGIN preview, CA validity) | S | High — zero friction improvement |
| 4 | Update INSTALL.md (config path, db-upgrade, --config-root) | S | High — corrects current errors |
| 5 | New `docs/installer_reference.md` | L | Medium — reference documentation |
| 6 | Help panels for remaining screens | S | Medium — consistent experience |
| 7 | Redis connectivity check | S | Medium — saves a common debugging cycle |
| 8 | Headless / answer-file mode | L | Medium — enables automation |

Items 1–4 can be shipped as a single focused PR. Items 5–8 are follow-on work.

---

## 6. Out of Scope

- Interactive proxy configuration (too many variants; config snippets remain the
  recommended approach)
- Automatic systemd unit file generation (was mentioned in `docs/installer.md`
  original proposal but not implemented; remains out of scope for this proposal)
- Wizard-style "undo" navigation beyond the existing `← Back` buttons
- Internationalisation of help text
