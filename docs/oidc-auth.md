# X2FA — OIDC & Authentication

X2FA implements the OpenID Connect Core 1.0 specification with extensions for
FIDO2 / TOTP two-factor authentication.

## 1. Supported OIDC Features

| Feature | Status |
|---------|--------|
| Authorization Code Flow | ✅ Required |
| PKCE (S256) | ✅ Mandatory (`plain` rejected) |
| ID Tokens (ES256) | ✅ EC P-256 signatures |
| JWKS Endpoint | ✅ `/.well-known/jwks.json` |
| OpenID Discovery | ✅ `/.well-known/openid-configuration` |
| Nonce | ✅ Optional in code flow |
| Scopes | `openid`, `app:setup` |

## 2. Discovery Document

```
GET /.well-known/openid-configuration
```

Returns:

```json
{
  "issuer": "https://<domain>",
  "authorization_endpoint": "https://<domain>/authorize",
  "token_endpoint": "https://<domain>/token",
  "jwks_uri": "https://<domain>/.well-known/jwks.json",
  "response_types_supported": ["code"],
  "subject_types_supported": ["public"],
  "id_token_signing_alg_values_supported": ["ES256"],
  "scopes_supported": ["openid", "app:setup"],
  "token_endpoint_auth_methods_supported": [
    "tls_client_auth",
    "private_key_jwt",
    "self_signed_tls_client_auth",
    "client_secret_jwt",
    "client_secret_post",
    "client_secret_basic"
  ],
  "code_challenge_methods_supported": ["S256"],
  "grant_types_supported": ["authorization_code"],
  "claims_supported": [
    "sub", "iss", "aud", "exp", "iat", "auth_time", "nonce"
  ]
}
```

## 3. Client Authentication Methods

X2FA supports six client authentication methods for the Token Endpoint.

### 3.1 PKI-Based Methods

#### `tls_client_auth` (mTLS)

The client presents a certificate signed by a trusted CA during the TLS
handshake. X2FA extracts the `client_id` from the certificate's CN.

**Requirements:**
- Trusted CA registered via `flask add-ca`
- Client certificate issued via `flask issue-client-cert`
- TLS mutual authentication configured in reverse proxy

**Flow:**
```
Client ── TLS ClientHello (with client cert) ──► X2FA
                ▲ TLS CertificateVerify ◄─────────
```

#### `private_key_jwt`

The client signs a JWT assertion with its private key and sends it as
`client_assertion` and `client_assertion_type` parameters. X2FA fetches
the client's public key from the `jwks_uri`.

**Requirements:**
- Trusted CA registered (for client cert issuance)
- Client exposes JWKS endpoint at `jwks_uri`
- Client stores private key securely

**JWT Claims:**
```json
{
  "iss": "<client_id>",
  "sub": "<client_id>",
  "aud": "https://<domain>",
  "exp": <unix_timestamp>,
  "iat": <unix_timestamp>,
  "jti": "<unique_id>"
}
```

**SSL Verification:** JWKS fetch uses `ssl.CERT_REQUIRED` with
`check_hostname=True` to prevent MITM attacks.

### 3.2 Self-Signed TLS

#### `self_signed_tls_client_auth`

The client presents a self-signed certificate. X2FA verifies the certificate
against an imported CA certificate (which is actually the client's own cert).

**Requirements:**
- Client certificate imported via `flask add-ca`
- Certificate CN must match `client_id`

### 3.3 Shared Secret Methods

#### `client_secret_jwt`

The client signs a JWT using the shared secret as an HMAC key (HS256).

**Requirements:**
- Shared secret generated via `flask generate-secret` or installer
- Secret stored Fernet-encrypted in the database

#### `client_secret_post`

The shared secret is sent as `client_secret` in the POST body.

#### `client_secret_basic`

The shared secret is sent as part of the `Authorization: Basic` header
(`base64(client_id:client_secret)`).

**Security Note:** Shared secrets are Fernet-encrypted at rest. The
plaintext secret is only shown once during client creation or installer
setup.

## 4. Authorization Endpoint

### `GET /authorize`

The authorization endpoint operates in two phases:

#### Phase 1 — Validation & 2FA Trigger

```
GET /authorize?client_id=rp1&redirect_uri=https://rp1/callback&
  code_challenge=E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM&
  code_challenge_method=S256&scope=openid&login_hint=user1
```

**Required Parameters:**

| Parameter | Required | Description |
|-----------|----------|-------------|
| `client_id` | Yes | Registered client identifier |
| `redirect_uri` | Yes | Must match a registered URI |
| `code_challenge` | Yes | PKCE code challenge (Base64url) |
| `code_challenge_method` | Yes | Must be `S256` |
| `scope` | Yes | Must include `openid` |
| `login_hint` | Yes | User identifier for 2FA |

**Optional Parameters:**

| Parameter | Description |
|-----------|-------------|
| `state` | Opaque value returned in redirect |
| `nonce` | Random value for ID token |
| `ui_locales` | Preferred UI language |

**Validation:**
- Client must exist and be active
- `redirect_uri` must match a registered URI
- `scope` must include `openid`
- `code_challenge_method` must be `S256` (plain rejected)

**On Success:**
- Stores OIDC params in Flask session (`session["oidc_request"]`)
- Sets `session["user_id"] = login_hint`
- Sets `session["2fa_verified"] = False`
- Redirects to `/verify` or `/setup` depending on scope

#### Phase 2 — Code Issuance

```
GET /authorize?client_id=rp1&redirect_uri=https://rp1/callback&...
```

Triggered after successful 2FA (`session["2fa_verified"] = True`):

- Authlib issues authorization code (60s TTL, single-use)
- Stores PKCE challenge for verification at `/token`
- Cleans up OIDC session state
- Redirects to `redirect_uri?code=...&state=...`

### PKCE Enforcement

PKCE S256 is **mandatory**. The `plain` challenge method is explicitly rejected.

```python
if code_challenge_method != "S256":
    abort(HTTPStatus.BAD_REQUEST, _("Only code_challenge_method=S256 is supported."))
```

## 5. Token Endpoint

### `POST /token`

Exchanges an authorization code for tokens.

**Required Parameters:**

| Parameter | Description |
|-----------|-------------|
| `grant_type` | Must be `authorization_code` |
| `code` | Authorization code from `/authorize` |
| `code_verifier` | PKCE code verifier |
| `client_id` | Client identifier |
| `client_assertion` | JWT assertion (for `private_key_jwt`) |
| `client_secret` | Shared secret (for `client_secret_*` methods) |

**Token Response:**

```json
{
  "id_token": "<ES256-signed JWT>",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

**ID Token Claims:**

| Claim | Description |
|-------|-------------|
| `sub` | User identifier |
| `iss` | Issuer (`https://<domain>`) |
| `aud` | Client ID |
| `exp` | Expiration (60s from issue) |
| `iat` | Issued at |
| `auth_time` | 2FA verification timestamp |
| `nonce` | Nonce from request (if provided) |
| `amr` | `["webauthn"]` or `["totp"]` or `["backup"]` |

## 6. JWKS Endpoint

### `GET /.well-known/jwks.json`

Returns public keys for ID token signature verification.

```json
{
  "keys": [
    {
      "kty": "EC",
      "crv": "P-256",
      "x": "...",
      "y": "...",
      "kid": "<key_id>",
      "use": "sig",
      "alg": "ES256"
    }
  ]
}
```

Only active, non-expired keys are returned.

## 7. 2FA Methods

After `/authorize` Phase 1, the user is redirected to one of:

### Login Flow (`/verify`)

1. **GET /verify** — Generates WebAuthn challenge, returns `verify.html`
2. **POST /verify/complete** — Verifies WebAuthn signature
3. On success: `session["2fa_verified"] = True`, redirect to `/authorize`

If no WebAuthn credentials exist:
- Falls back to TOTP if a verified TOTP secret exists
- Returns OIDC error `access_denied` if no 2FA method is registered

### Registration Flow (`/setup`)

1. **GET /setup** — Method selection (WebAuthn / TOTP)
2. **GET /setup/webauthn** — Generates WebAuthn registration challenge
3. **POST /setup/complete** — Verifies registration, stores credential
4. **GET /setup/done** — Displays backup codes (one-time)

TOTP setup:
1. **GET /totp/setup** — Generates secret, shows QR code
2. **POST /totp/setup/verify** — Verifies test code, generates backup codes
3. Redirects to `/setup/done`

### Backup Code Verification

1. **GET /backup/verify** — Returns backup code input form
2. **POST /backup/verify** — Checks code against bcrypt hashes
3. On success: `session["2fa_verified"] = True`

## 8. Security Considerations

### Nonce Replay Protection

AuthorizationCodes werden nach Token-Exchange nicht physisch gelöscht (nur `used=True` markiert).
`cleanup-codes` entfernt sie erst nach 1h. Das ermöglicht dem RP, das ID-Token
(60s Expiry) auch nach dem Token-Exchange zu verarbeiten. Der echte Replay-Schutz
kommt daher, dass der AuthorizationCode selbst nicht erneut getauscht werden kann.

### Session Security

- OIDC parameters stored in server-side Flask session (not URLs)
- Session cleared after code issuance
- Error redirects use `_oidc_error_redirect()` to prevent state leakage

### Rate Limiting

All verification endpoints are rate-limited:

| Endpoint | Purpose |
|----------|---------|
| `/authorize` | Prevent brute-force OIDC requests |
| `/token` | Prevent code replay |
| `/verify/complete` | Prevent WebAuthn brute-force |
| `/setup/complete` | Prevent registration abuse |
| `/totp/setup/verify` | Prevent TOTP brute-force |
| `/totp/verify` | Prevent TOTP brute-force |
| `/backup/verify` | Prevent backup code brute-force |

### Challenge TTL

WebAuthn and TOTP challenges expire after a configurable number of minutes
(default: 5 minutes). Challenges are single-use.