# Security Policy

X2FA is an authentication and identity service. We take security reports
seriously and ask for responsible disclosure.

## Reporting a Vulnerability

**Please do NOT open a public issue for security vulnerabilities.**

Preferred channels (in order):

1. **GitHub Private Vulnerability Reporting** —
   [Report a vulnerability](../../security/advisories/new) via GitHub Security Advisories.
2. **Email** — <!-- TODO: add your security contact address, e.g. security@example.com -->

Please include:

- Affected version(s) and deployment context (database, proxy, auth method)
- Steps to reproduce / proof of concept
- Impact assessment (what an attacker could achieve)

You will receive an acknowledgement within **72 hours**. We aim to provide a
fix or mitigation within **14 days** for critical issues, and will coordinate
the disclosure timeline with you. Credit in the release notes is given unless
you prefer to remain anonymous.

## Supported Versions

| Version | Supported |
|---------|-----------|
| latest release | ✅ |
| older releases | ❌ (please upgrade) |

## Scope

In scope:

- The X2FA server (`src/x2fa/`), the installer (`installer/`), and the Flask CLI
- OIDC/OAuth2 protocol implementation (authorization, token, JWKS, discovery endpoints)
- WebAuthn/FIDO2, TOTP, and backup code verification logic
- Client authentication (all six methods, PKI handling)
- Cryptographic key storage and rotation
- Session handling, rate limiting, audit logging

Out of scope:

- Vulnerabilities in third-party dependencies without a demonstrated exploit
  path in X2FA (report these upstream; run `pip-audit` for known CVEs)
- Misconfiguration of the surrounding infrastructure (reverse proxy, TLS,
  database) — but hardening suggestions are always welcome
- Self-XSS or attacks requiring physical access to the server

## Security Model (Summary)

X2FA's security design is documented in detail in
[docs/security.md](docs/security.md). Highlights:

- **PKCE S256 mandatory** — `plain` is rejected
- **ES256 ID tokens** — EC P-256, private keys Fernet-encrypted at rest
- **Secrets at rest** — Fernet (AES-128-CBC) for client secrets, TOTP secrets,
  and signing keys; bcrypt (12 rounds) for backup codes
- **GDPR-compliant audit log** — IPs stored as `SHA256(ip + X2FA_SECRET)`
- **Session-based OIDC state** — no OIDC parameters in URLs; session ID rotated
  after 2FA; error redirects strip sensitive state
- **Anti-replay** — single-use challenges (5 min TTL), TOTP window check,
  sign-count regression detection, single-use authorization codes
- **Rate limiting** — all verification endpoints, Redis backend for multi-worker
- **Input validation** — path traversal protection, SSL-verified JWKS fetches,
  parameterized queries only

## Hardening Recommendations

- Never run X2FA as root; use a dedicated user
- Terminate TLS at a reverse proxy (nginx/Caddy/Traefik) with HSTS
- Use Redis-backed rate limiting when running multiple gunicorn workers
- Restrict `~/.local/share/x2fa/` permissions (`0700`); CA keys are written `0600`
- Rotate signing keys periodically: `flask rotate-keys`
- Schedule `flask cleanup-codes` (e.g. via systemd timer or cron)
