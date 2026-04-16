# X2FA — Client Authentication Options

**Status:** Proposal  
**Date:** 2026-04-15  
**Context:** X2FA currently supports only PKI-based client auth (`tls_client_auth` and
`private_key_jwt`). This document proposes extending the system with additional
authentication methods so that operators can choose the trust model that best fits their
deployment constraints.

---

## 1. Motivation

The current PKI-only approach is the most secure option and should remain the default and
the recommended choice for production deployments. However, several legitimate scenarios
make it impractical:

- Development environments where provisioning a CA and client certificates is overhead.
- Integrations with third-party services that cannot be configured to present mTLS
  certificates.
- Operators who need a quick onboarding path before migrating to PKI.

This proposal defines a menu of **five options (A–E)** that span the trust-model spectrum
from full PKI to simple shared secrets.

---

## 2. Options Overview

| # | Method string(s) | Trust root | Shared secret? | Complexity |
|---|---|---|---|---|
| A | `tls_client_auth`, `private_key_jwt` | CA-signed X.509 / JWKS | No | High |
| B | `self_signed_tls_client_auth` | Cert fingerprint pinning | No | Medium |
| C | `client_secret_jwt` | HMAC-signed JWT | Yes (Fernet-enc.) | Medium |
| D | *(emergent — A + E per client)* | Mixed per client | Mixed | — |
| E | `client_secret_post`, `client_secret_basic` | Shared secret in request | Yes (Fernet-enc.) | Low |

Option D is not a distinct implementation: it emerges automatically once the system
supports both PKI methods (A/B) and secret methods (C/E), because each client carries its
own `token_endpoint_auth_method`.

---

## 3. Detailed Specification

### 3.1 Option A — CA-Signed PKI (current, unchanged)

**Methods:** `tls_client_auth` | `private_key_jwt`

`tls_client_auth`: The reverse proxy terminates TLS, verifies the client certificate
against the `trusted_ca` table, and forwards the PEM-encoded certificate in the
`X-Client-Certificate` header. The Flask auth handler parses the certificate, extracts the
`CN`, and looks up the matching `OIDCClient` by `client_id`.

`private_key_jwt`: The client sends a JWT signed with its EC private key. Authlib's
built-in `PrivateKeyJWTClientAuth` handler fetches the client's JWKS from `jwks_uri`,
verifies the signature, and checks `aud` == token endpoint URL.

No schema changes required.

---

### 3.2 Option B — Self-Signed Certificate (Fingerprint-Pinned)

**Method string:** `self_signed_tls_client_auth`

Instead of a CA-signed chain, the client generates its own self-signed certificate.
X2FA pins the certificate's SHA-256 fingerprint rather than validating a chain.

**Schema addition** to `OIDCClient`:

```python
# Option B: DER-encoded SHA-256 fingerprint of the pinned self-signed cert.
# Stored as hex string for readability (e.g. "aa:bb:cc:...").
client_cert_fingerprint = Column(String(95), nullable=True)
```

*(95 chars = 32 bytes × 3 chars including colons)*

**Auth handler logic:**

```python
def verify_self_signed_tls(client_id: str, request) -> bool:
    cert_pem = request.headers.get("X-Client-Certificate")
    if not cert_pem:
        return False
    cert = x509.load_pem_x509_certificate(unquote(cert_pem).encode())
    fingerprint = cert.fingerprint(hashes.SHA256()).hex(":")
    client = db_session.get(OIDCClient, client_id)
    return (
        client is not None
        and client.token_endpoint_auth_method == "self_signed_tls_client_auth"
        and client.client_cert_fingerprint == fingerprint
    )
```

**Proxy configuration:** Same as `tls_client_auth` but `ssl_verify_client optional` (no
CA chain to verify — the proxy passes whatever the client presents).

**CLI:**

```
flask add-client <id> <redirect_uri> \
    --method self_signed_tls_client_auth \
    --cert /path/to/client_self_signed.pem
```

The command reads the PEM file, computes `SHA256(DER)`, stores the hex fingerprint.

**Rotation:** When the client regenerates its cert, call:

```
flask update-client-cert <client_id> --cert /path/to/new_cert.pem
```

---

### 3.3 Option C — `client_secret_jwt` (HMAC-Signed JWT)

**Method string:** `client_secret_jwt`

The client signs a JWT with a shared secret using `HS256`. X2FA verifies the HMAC
signature. Defined in RFC 7523 §2.2.

**Why Fernet, not bcrypt:** HMAC verification requires the plaintext secret. bcrypt is
one-way and cannot be used. The secret must be recoverable, hence Fernet symmetric
encryption (same pattern used for TOTP secrets and signing keys).

**Schema addition** to `OIDCClient`:

```python
# Options C / E: Fernet-encrypted client secret.
# Plaintext is a 32-byte random secret (hex-encoded = 64 chars shown to admin once).
client_secret_encrypted = Column(LargeBinary, nullable=True)
```

**Auth handler logic:**

```python
def verify_client_secret_jwt(client_id: str, assertion: str, token_endpoint_url: str) -> bool:
    fernet = CryptoService(current_app.config.x2fa_security.SECRET_KEY).get_fernet()
    client = db_session.get(OIDCClient, client_id)
    if not client or not client.client_secret_encrypted:
        return False
    secret = fernet.decrypt(client.client_secret_encrypted)  # bytes
    try:
        jwt.decode(
            assertion,
            secret,
            algorithms=["HS256"],
            audience=token_endpoint_url,
            options={"require": ["iss", "sub", "aud", "exp", "jti"]},
        )
        return True
    except jwt.PyJWTError:
        return False
```

**CLI:**

```
flask add-client <id> <redirect_uri> --method client_secret_jwt
```

A 32-byte secret is auto-generated, Fernet-encrypted, and stored. The plaintext hex
string is printed **once** and never stored. Operators must record it immediately.

**Secret rotation:**

```
flask rotate-client-secret <client_id>
```

---

### 3.4 Option D — Mixed PKI + Secret (Emergent)

No dedicated implementation needed. Once A/B and C/E are both supported, any combination
is automatically available because each `OIDCClient` row carries its own
`token_endpoint_auth_method`. The dispatcher routes by method string.

---

### 3.5 Option E — `client_secret_post` / `client_secret_basic`

**Method strings:** `client_secret_post` | `client_secret_basic`

The client sends its secret directly in the POST body (`client_secret` parameter) or as
HTTP Basic credentials. Authlib supports both natively; X2FA only needs to supply the
secret to the comparison.

**Same schema column as Option C:** `client_secret_encrypted` (reused).

**Auth handler logic (post):**

```python
def verify_client_secret_post(client_id: str, client_secret: str) -> bool:
    fernet = CryptoService(current_app.config.x2fa_security.SECRET_KEY).get_fernet()
    client = db_session.get(OIDCClient, client_id)
    if not client or not client.client_secret_encrypted:
        return False
    stored = fernet.decrypt(client.client_secret_encrypted).decode()
    return hmac.compare_digest(stored, client_secret)  # constant-time
```

`client_secret_basic` decodes the `Authorization: Basic …` header and applies the same
comparison. Authlib's `ClientSecretBasicAuth` can be subclassed to inject this logic.

**CLI:** Same as Option C:

```
flask add-client <id> <redirect_uri> --method client_secret_post
flask add-client <id> <redirect_uri> --method client_secret_basic
```

**Warning:** `client_secret_post` and `client_secret_basic` transmit the secret on every
request. They are only acceptable over TLS-terminated HTTPS. They provide no forward
secrecy. Use only for low-risk integrations or temporary setups.

---

## 4. Schema Migration

Two nullable columns are added to `oidc_client`. Existing rows are unaffected (both
columns default to `NULL`).

```sql
ALTER TABLE oidc_client
    ADD COLUMN client_cert_fingerprint  VARCHAR(95)   DEFAULT NULL,
    ADD COLUMN client_secret_encrypted  BLOB          DEFAULT NULL;
```

For fresh installations, `flask init-db` picks up the new columns automatically.

For existing installations running SQLite:

```bash
sqlite3 /path/to/x2fa.db \
  "ALTER TABLE oidc_client ADD COLUMN client_cert_fingerprint TEXT;
   ALTER TABLE oidc_client ADD COLUMN client_secret_encrypted BLOB;"
```

---

## 5. Constants and Method Strings

Add to `src/x2fa/constants.py`:

```python
# Additional token endpoint auth methods
AUTH_METHOD_SELF_SIGNED_TLS  = "self_signed_tls_client_auth"
AUTH_METHOD_CLIENT_SECRET_JWT  = "client_secret_jwt"
AUTH_METHOD_CLIENT_SECRET_POST = "client_secret_post"
AUTH_METHOD_CLIENT_SECRET_BASIC = "client_secret_basic"

ALL_AUTH_METHODS = [
    AUTH_METHOD_TLS_CLIENT_AUTH,       # A — CA-signed mTLS
    AUTH_METHOD_PRIVATE_KEY_JWT,       # A — JWKS-verified JWT
    AUTH_METHOD_SELF_SIGNED_TLS,       # B — fingerprint-pinned self-signed
    AUTH_METHOD_CLIENT_SECRET_JWT,     # C — HMAC-signed JWT
    AUTH_METHOD_CLIENT_SECRET_POST,    # E — secret in POST body
    AUTH_METHOD_CLIENT_SECRET_BASIC,   # E — Basic auth
]
```

---

## 6. Auth Dispatcher

A central dispatcher in `init_app/security.py` (or a new `services/client_auth.py`) maps
method strings to handler functions. Authlib's `ClientAuthMixin` supports registering
custom auth methods via `oauth.register_client_auth_method(method_string, handler_fn)`.

```python
from authlib.integrations.flask_oauth2 import AuthorizationServer

def register_auth_methods(oauth: AuthorizationServer) -> None:
    # A — already registered by Authlib defaults (tls_client_auth, private_key_jwt)

    # B
    oauth.register_client_auth_method(
        AUTH_METHOD_SELF_SIGNED_TLS, verify_self_signed_tls
    )
    # C
    oauth.register_client_auth_method(
        AUTH_METHOD_CLIENT_SECRET_JWT, verify_client_secret_jwt
    )
    # E
    oauth.register_client_auth_method(
        AUTH_METHOD_CLIENT_SECRET_POST, verify_client_secret_post
    )
    oauth.register_client_auth_method(
        AUTH_METHOD_CLIENT_SECRET_BASIC, verify_client_secret_basic
    )
```

---

## 7. CLI Summary

| Command | Purpose |
|---|---|
| `flask add-client <id> <uri> --method tls_client_auth` | Option A: CA-signed mTLS |
| `flask add-client <id> <uri> --method private_key_jwt --jwks-uri <url>` | Option A: JWKS JWT |
| `flask add-client <id> <uri> --method self_signed_tls_client_auth --cert <path>` | Option B: pin self-signed cert |
| `flask add-client <id> <uri> --method client_secret_jwt` | Option C: auto-generates secret |
| `flask add-client <id> <uri> --method client_secret_post` | Option E: auto-generates secret |
| `flask add-client <id> <uri> --method client_secret_basic` | Option E: auto-generates secret |
| `flask update-client-cert <id> --cert <path>` | Option B: rotate pinned cert |
| `flask rotate-client-secret <id>` | Options C/E: rotate secret |
| `flask list-clients` | Show all clients and their auth methods |
| `flask revoke-client <id>` | Deactivate a client |

For Options C and E, `add-client` prints the plaintext secret exactly once:

```
Client ID:      my-app
Auth method:    client_secret_jwt
Client secret:  a3f2...  ← record this now, it will not be shown again
```

---

## 8. Installer TUI Changes

`installer/screens/client.py` RadioSet is extended from 2 to 6 options:

```
( ) tls_client_auth          — CA-signed mTLS  [recommended]
( ) private_key_jwt          — JWKS-verified JWT
( ) self_signed_tls_client_auth  — self-signed cert, fingerprint-pinned
( ) client_secret_jwt        — HMAC-signed JWT
( ) client_secret_post       — secret in POST body  [not recommended for production]
( ) client_secret_basic      — HTTP Basic auth      [not recommended for production]
```

The CA setup screen (`ca_setup.py`) is shown only when the selected method is
`tls_client_auth` or `private_key_jwt`. For `self_signed_tls_client_auth`, the installer
instead prompts for the path to the self-signed cert. For secret methods, no CA screen is
shown and no certificates are generated.

---

## 9. Security Comparison

| | A (PKI) | B (self-signed) | C (secret_jwt) | E (secret_post/basic) |
|---|---|---|---|---|
| Secret transmitted per request | No | No | No (JWT signature) | **Yes** |
| Forward secrecy | Yes (EC key) | Yes (EC key) | No | No |
| Requires reverse proxy with mTLS | Yes | Yes (pass-through) | No | No |
| CA infrastructure required | Yes | No | No | No |
| Replay protection | mTLS session | mTLS session | JWT `jti` + `exp` | None built-in |
| Rotation procedure | Re-issue cert | `update-client-cert` | `rotate-client-secret` | `rotate-client-secret` |
| **Recommended for production** | **Yes** | Acceptable | With caution | **No** |

---

## 10. Implementation Order

## Implementation Notes

**Current status:** Only Option A (`tls_client_auth`, `private_key_jwt`) is implemented.
The remaining options (B, C, E) are fully specified in this document but not yet implemented.
See `docs/todo.md` for the current task list.

---

## 11. Non-Goals

- `none` auth method (no authentication) — rejected; would allow any request to obtain
  tokens.
- `private_key_jwt` with symmetric keys — conflates C and A; use `client_secret_jwt` for
  HMAC.
- Storing plaintext secrets anywhere — all secrets that must be recoverable are
  Fernet-encrypted using `X2FA_SECRET` as the key material.
- Automatic secret display after first registration — secrets are shown once, at
  `add-client` time. There is no "show secret" command.
