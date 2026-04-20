"""Configuration Review screen — read-only summary before the execute step."""

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import Screen
from textual.widgets import Button, Checkbox, Footer, Header, Static


class ReviewScreen(Screen):
    def compose(self) -> ComposeResult:
        cfg = self.app.config

        yield Header()
        with Container(id="panel"):
            yield Static("Review: Configuration Summary", classes="screen-title")
            yield Static(
                "[dim]Review all settings before installation begins. "
                "Use ← Back to correct any value.[/]",
                markup=True,
                classes="hint",
            )

            # ── Database ───────────────────────────────────────────────────
            yield Static("DATABASE", classes="review-section")
            yield Static(f"  Type:  {cfg.db_type or 'sqlite'}", classes="review-row")
            if cfg.db_type and cfg.db_type != "sqlite":
                yield Static(f"  URI:   {cfg.db_uri or '(not set)'}", classes="review-row")
            else:
                default_db = str(cfg._data_dir() / "db.sqlite")
                yield Static(f"  Path:  {default_db}", classes="review-row")

            # ── Domain ─────────────────────────────────────────────────────
            yield Static("DOMAIN", classes="review-section")
            yield Static(f"  Domain:  {cfg.domain or '(not set)'}", classes="review-row")
            yield Static(
                f"  Origin:  https://{cfg.domain}" if cfg.domain else "  Origin:  (not set)",
                classes="review-row",
            )
            yield Static(f"  Proxy:   {cfg.proxy_type or 'caddy'}", classes="review-row")

            # ── Security ───────────────────────────────────────────────────
            yield Static("SECURITY", classes="review-section")
            sk = cfg.secret_key or ""
            ss = cfg.secret_salt or ""
            yield Static(
                f"  SECRET_KEY:   {sk[:8]}…{sk[-4:]}  ({len(sk)} hex chars)" if len(sk) >= 12
                else f"  SECRET_KEY:   {sk or '(not set)'}",
                classes="review-row",
            )
            yield Static(
                f"  SECRET_SALT:  {ss[:8]}…{ss[-4:]}  ({len(ss)} hex chars)" if len(ss) >= 12
                else f"  SECRET_SALT:  {ss or '(not set)'}",
                classes="review-row",
            )
            if cfg.use_redis:
                yield Static(f"  Rate limiter: Redis  {cfg.redis_uri}", classes="review-row")
            else:
                yield Static("  Rate limiter: memory://  (single worker)", classes="review-row")

            # ── Client ─────────────────────────────────────────────────────
            yield Static("CLIENT", classes="review-section")
            yield Static(f"  Client ID:    {cfg.client_id or '(not set)'}", classes="review-row")
            yield Static(f"  Redirect URI: {cfg.client_redirect_uri or '(not set)'}", classes="review-row")
            yield Static(f"  Auth method:  {cfg.client_auth_method or 'tls_client_auth'}", classes="review-row")
            if cfg.client_auth_method == "private_key_jwt":
                yield Static(f"  JWKS URI:     {cfg.client_jwks_uri or '(not set)'}", classes="review-row")
            elif cfg.client_auth_method == "self_signed_tls_client_auth":
                yield Static(f"  Cert path:    {cfg.client_self_signed_cert_path or '(not set)'}", classes="review-row")

            # ── CA (only for PKI methods) ──────────────────────────────────
            method = cfg.client_auth_method or "tls_client_auth"
            if method in {"tls_client_auth", "private_key_jwt"}:
                yield Static("CERTIFICATE AUTHORITY", classes="review-section")
                action = cfg.ca_action or "generate"
                yield Static(
                    f"  Action:   {'Generate new CA' if action == 'generate' else 'Import existing CA'}",
                    classes="review-row",
                )
                yield Static(f"  Name:     {cfg.ca_name or '(not set)'}", classes="review-row")
                if action == "generate":
                    days = cfg.ca_validity_days
                    years = days / 365
                    yield Static(f"  CN:       {cfg.ca_cn or '(not set)'}", classes="review-row")
                    yield Static(f"  Validity: {days} days (≈ {years:.1f} years)", classes="review-row")
                    yield Static(f"  Key:      {cfg.ca_key_path or '(not set)'}", classes="review-row")
                    yield Static(f"  Cert:     {cfg.ca_cert_path or '(not set)'}", classes="review-row")
                else:
                    yield Static(f"  Cert:     {cfg.ca_import_path or '(not set)'}", classes="review-row")

            # ── Deployment ─────────────────────────────────────────────────
            yield Static("DEPLOYMENT", classes="review-section")
            yield Checkbox(
                "Enable and start systemd service automatically after install",
                id="enable_systemd",
                value=cfg.enable_systemd,
            )

            with Container(id="buttons"):
                yield Button("← Back", id="back")
                yield Button("Confirm & Install →", id="confirm", variant="success")
        yield Footer()

    def on_checkbox_changed(self, event: Checkbox.Changed) -> None:
        if event.checkbox.id == "enable_systemd":
            self.app.config.enable_systemd = event.value

    def on_button_pressed(self, event: Button.Pressed) -> None:
        match event.button.id:
            case "back":
                self.app.pop_screen()
            case "confirm":
                from installer.screens.execute import ExecuteScreen
                self.app.push_screen(ExecuteScreen())
