# Migration Plan: client_secret → PKI (Self-Sovereign Keys)

Replaces shared-secret client authentication with X.509/mTLS and `private_key_jwt`.
The migration is designed so that each step leaves the system in a working state.
Steps 1+2 and Steps 3+4 are independent and can be developed in parallel.
The only breaking change is in Step 6.

---

## Step 1: Add `TrustedCA` model

**Files:** `src/x2fa/models.py`

Add a new SQLAlchemy model `TrustedCA` to the existing models file:

```python
class TrustedCA(Base):
    __tablename__ = "trusted_ca"

    id          = Column(Integer, primary_key=True, autoincrement=True)
    name        = Column(String(100), nullable=False, unique=True)
    cert_pem    = Column(Text, nullable=False)        # PEM-encoded root/intermediate cert
    active      = Column(Boolean, nullable=False, default=True)
    created_at  = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    expires_at  = Column(DateTime, nullable=True)     # None = unknown / not checked

    def verify_certificate(self, client_cert_pem: str) -> dict:
        """
        Validates client_cert_pem against this CA.
        Returns {'valid': True, 'client_id': <CN>} or {'valid': False, 'reason': <str>}.
        Uses cryptography.x509 to check signature, validity period, and extracts CN as client_id.
        """
```

The table is created automatically by `db.create_all()` on next startup (no Alembic migration
required for SQLite; PostgreSQL/MySQL deployments need a migration script).

**Done when:** `TrustedCA` rows can be inserted and queried without errors.

---

## Step 2: CA management CLI commands

**Files:** `src/x2fa/cli.py`

Add four new Flask CLI commands. Import `TrustedCA` from `models`.

### `flask add-ca <name> <cert_path>`
Reads a PEM file from `cert_path`, parses the certificate with `cryptography.x509` to extract
`expires_at`, then inserts a `TrustedCA` row. Prints a confirmation with name and fingerprint.
Rejects the file if it is not a valid X.509 certificate.

### `flask list-cas`
Queries all `TrustedCA` rows. Prints name, active status, expiry date, and SHA256 fingerprint
for each CA. Warns if any active CA is expired or expires within 30 days.

### `flask revoke-ca <name>`
Sets `active = False` on the named CA. Does not delete the row (audit trail).
Prints a warning if active `OIDCClient` rows use this CA (detected via `client_cert_fingerprint`
matching certs signed by this CA — or simply print a general "verify your clients" warning).

### `flask issue-client-cert <client_id>`
Generates a new EC P-256 key pair, creates an X.509 certificate with `CN=<client_id>`,
signs it with the specified CA (`--ca <name>`, required option), and writes three files
to the output directory (`--output`, default: current directory):
- `<client_id>.key.pem` — private key (mode 0600)
- `<client_id>.cert.pem` — signed certificate
- `<client_id>.ca.pem` — CA certificate (for trust bundle)

Validity defaults to 90 days (`--validity-days`).

**Done when:** All four commands work end-to-end against a locally generated test CA.

---

## Step 3: Extend `OIDCClient` model (additive, no breaking change)

**Files:** `src/x2fa/models.py`

Add three new nullable columns to `OIDCClient`. Keep `client_secret` and all existing methods
untouched — existing clients continue to work without any changes.

```python
token_endpoint_auth_method = Column(
    String(50), nullable=False, default="client_secret_post"
)
client_cert_fingerprint = Column(String(255), nullable=True)  # SHA256, optional pinning
jwks_uri = Column(String(255), nullable=True)                  # for private_key_jwt clients
```

Update `check_token_endpoint_auth_method()` to also accept `tls_client_auth` and
`private_key_jwt` (in addition to the existing `client_secret_*` methods):

```python
def check_token_endpoint_auth_method(self, method: str) -> bool:
    return method == self.token_endpoint_auth_method
```

**Done when:** Existing clients still authenticate normally; new columns are present in the DB.

---

## Step 4: Extend `add-client` CLI

**Files:** `src/x2fa/cli.py`

Extend the `add-client` command with two new options:

- `--method` — `tls_client_auth` | `private_key_jwt` | `client_secret_post` (default: `client_secret_post`)
- `--jwks-uri` — JWKS URL for `private_key_jwt` clients (required when `--method private_key_jwt`)

When `--method tls_client_auth` is given:
- `--secret` is ignored (no client secret generated or stored)
- `client_secret` is set to `""` (empty, satisfies NOT NULL until Step 6 removes the column)

When `--method private_key_jwt` is given:
- Same as above, plus `jwks_uri` is saved.

Print the chosen auth method in the confirmation output. Update `list-clients` to show
`token_endpoint_auth_method` alongside each client entry.

**Done when:** `add-client --method tls_client_auth` creates a client row with the correct
`token_endpoint_auth_method` value and no usable secret.

---

## Step 5: Implement new auth methods in `grants.py`

**Files:** `src/x2fa/oidc/grants.py`

This step adds mTLS and `private_key_jwt` support alongside the existing `client_secret` auth.
No existing behaviour is removed yet.

### 5a: Extend `TOKEN_ENDPOINT_AUTH_METHODS`

```python
TOKEN_ENDPOINT_AUTH_METHODS = [
    "tls_client_auth",
    "private_key_jwt",
    "client_secret_post",
    "client_secret_basic",
]
```

### 5b: Add `_authenticate_via_mtls(request)`

Reads `X-Client-Certificate` from the request headers (forwarded by the reverse proxy).
Iterates over all active `TrustedCA` rows and calls `ca.verify_certificate(cert_pem)`.
On the first match, looks up the `OIDCClient` by the extracted CN. Raises `OAuth2Error`
`invalid_client` if no CA accepts the certificate or the client is inactive.

The reverse proxy must be configured to forward the client certificate as a PEM-encoded
header (nginx: `proxy_set_header X-Client-Certificate $ssl_client_escaped_cert;`).

### 5c: Add `_authenticate_via_private_key_jwt(request)`

Reads `client_assertion` from the request form. Decodes the JWT header to extract the
`x5c` certificate chain. Validates the leaf certificate against active `TrustedCA` rows
using the same logic as 5b. If valid, extracts the public key from the certificate and
verifies the JWT signature (`RS256` or `ES256`). The audience must equal the token
endpoint URL. Raises `OAuth2Error` `invalid_client` on any failure.

### 5d: Override `authenticate_client(request)`

Dispatch based on `client.token_endpoint_auth_method`:

```python
def authenticate_client(self, request):
    method = request.client_metadata.get("token_endpoint_auth_method", "client_secret_post")
    if method == "tls_client_auth":
        return self._authenticate_via_mtls(request)
    elif method == "private_key_jwt":
        return self._authenticate_via_private_key_jwt(request)
    else:
        return super().authenticate_client(request)  # existing client_secret logic
```

**Done when:** A client registered with `--method tls_client_auth` can successfully exchange
a code for an ID token using a certificate issued in Step 2.

---

## Step 6: Remove `client_secret` (breaking change)

**Prerequisite:** Step 5 is tested and verified in the target environment.

**Files:** `src/x2fa/models.py`, `src/x2fa/cli.py`, `demo_rp/app.py`, tests

### 6a: Remove `client_secret` from `OIDCClient`
- Drop the `client_secret` column from the model and the DB (migration required).
- Remove `has_client_secret()`, `check_client_secret()`, `check_token_endpoint_auth_method()`
  (replaced by the updated version from Step 3).

### 6b: Remove `client_secret_*` from auth methods
- Remove `client_secret_post` and `client_secret_basic` from `TOKEN_ENDPOINT_AUTH_METHODS`.
- Remove the `super().authenticate_client()` fallback from the dispatcher.

### 6c: Update `add-client` CLI
- Remove `--secret` option entirely.
- Make `--method` required (or default to `tls_client_auth`).

### 6d: Update demo RP
- `demo_rp/app.py` must switch to mTLS or `private_key_jwt` for its token request.
- Issue a client certificate for the demo RP using `flask issue-client-cert`.

### 6e: Update tests
- Replace all `client_secret` fixtures and token-request helpers with certificate-based auth.

**Done when:** No `client_secret` reference remains in production code; all tests pass.
