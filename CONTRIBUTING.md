# Contributing to X2FA

Thanks for your interest! X2FA is a security-sensitive project — contributions
are held to a higher bar than average. Please read this guide before opening a PR.

## Ways to Contribute

- **Bug reports** — open an issue with version, config (sanitized!), and reproduction steps
- **Security issues** — see [SECURITY.md](SECURITY.md), never a public issue
- **Features** — open an issue first to discuss scope; unsolicited large PRs risk rejection
- **Documentation** — typos, clarifications, translations welcome anytime

## Development Setup

Requirements: Python ≥ 3.11, [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/<you>/x2fa.git && cd x2fa
uv venv && source .venv/bin/activate
uv pip install -e ".[installer,dev]"

# Use an isolated config/data root for development
export X2FA_HOME=/tmp/x2fa-dev

FLASK_APP=x2fa.wsgi_cli:app uv run flask init-db
FLASK_APP=x2fa.wsgi_cli:app uv run flask init-keys
FLASK_APP=x2fa.wsgi:app uv run flask run
```

## Testing

All PRs must pass the test suite:

```bash
uv run pytest tests/ -v          # full suite
uv run pytest tests/ -m unit -v  # fast unit tests (no DB, no I/O)
uv run pytest tests/e2e/ -v      # E2E tests (installer)
```

Rules:

- New features need tests; bug fixes need a regression test
- Pure logic → `unit` marker (must not touch DB, filesystem, or network)
- Never commit secrets, keys, or real certificates — tests use `X2FA_HOME` fixtures

## Code Style

- Follow the existing style; run the linters configured in CI before pushing
- Type annotations for public functions; keep the factory pattern (`create_app()`)
- Comments and docstrings in English
- No new dependencies without prior discussion in an issue

## Security-Specific Rules

These are non-negotiable in this codebase:

- **Never log secrets, tokens, challenges, codes, or plaintext IP addresses**
  (audit log stores `SHA256(ip + X2FA_SECRET)` only)
- All SQL via SQLAlchemy ORM or parameterized queries — no string formatting
- File paths from user input go through `_resolve_file()`
- New subprocess calls need a timeout (existing convention: 120 s)
- New secrets-at-rest use `CryptoService` (Fernet); password-like data uses bcrypt
- PKCE S256 must stay mandatory — do not weaken this, even behind a flag
- Session keys follow the existing pattern (`oidc_request`, `user_id`,
  `2fa_verified`, ...); clean up on error paths like `_oidc_error_redirect()`

## Translations

UI strings use Flask-Babel (German default). Mark new user-facing strings with
`_()` and update the message catalogs.

## Commit & PR Conventions

- Small, focused commits with imperative messages (`fix: reject plain PKCE method`)
- Rebase onto `main` before requesting review; no merge commits in PRs
- PR description: what, why, how tested
- One logical change per PR

## Database Migrations

- Schema changes need an Alembic migration
- Migrations must be non-destructive (`init-db` stamps + upgrades; no `DROP`)
- Test upgrades against an existing database, not just fresh installs

## License

By contributing, you agree that your contributions are licensed under the
project's license (see [LICENSE](LICENSE)).
