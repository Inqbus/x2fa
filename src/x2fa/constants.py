from datetime import datetime

# Sentinel datetimes — used instead of None to make intent explicit in DB columns.
#
# Both are timezone-naive because SQLAlchemy's DateTime column (without timezone=True)
# stores and retrieves naive datetimes in both SQLite and PostgreSQL (TIMESTAMP WITHOUT
# TIME ZONE). Using timezone-aware sentinels would cause equality checks to fail after
# a DB round-trip.
#
# "never used": far enough in the past that any delta-based check
# (e.g. TOTP replay window of 30 s) always passes.  totp_helpers.verify_code()
# treats naive datetimes as UTC via .replace(tzinfo=timezone.utc).
NEVER_USED    = datetime(1970, 1, 1)
# "never expires": satisfies "> datetime.now()" automatically so no special-casing
# is needed at query sites.
NEVER_EXPIRES = datetime(9999, 12, 31, 23, 59, 59)

# Audit action strings
ACTION_SETUP  = "setup"
ACTION_VERIFY = "verify"
ACTION_FAIL   = "fail"

# Audit method strings
METHOD_WEBAUTHN_PLATFORM = "webauthn_platform"
METHOD_WEBAUTHN_ROAMING  = "webauthn_roaming"
METHOD_TOTP              = "totp"
METHOD_BACKUP            = "backup"

# Token endpoint authentication methods (RFC 7591 / RFC 7523)
AUTH_METHOD_TLS_CLIENT_AUTH      = "tls_client_auth"
AUTH_METHOD_PRIVATE_KEY_JWT      = "private_key_jwt"
AUTH_METHOD_SELF_SIGNED_TLS      = "self_signed_tls_client_auth"
AUTH_METHOD_CLIENT_SECRET_JWT    = "client_secret_jwt"
AUTH_METHOD_CLIENT_SECRET_POST   = "client_secret_post"
AUTH_METHOD_CLIENT_SECRET_BASIC  = "client_secret_basic"

ALL_AUTH_METHODS = [
    AUTH_METHOD_TLS_CLIENT_AUTH,
    AUTH_METHOD_PRIVATE_KEY_JWT,
    AUTH_METHOD_SELF_SIGNED_TLS,
    AUTH_METHOD_CLIENT_SECRET_JWT,
    AUTH_METHOD_CLIENT_SECRET_POST,
    AUTH_METHOD_CLIENT_SECRET_BASIC,
]

# JWT client assertion type (RFC 7523)
JWT_BEARER_ASSERTION_TYPE = "urn:ietf:params:oauth:client-assertion-type:jwt-bearer"

# Cryptography — not admin-tunable, fixed by design
BCRYPT_ROUNDS      = 12   # bcrypt cost factor for backup-code hashes
BACKUP_CODES_COUNT = 10   # number of single-use backup codes generated per registration
CHALLENGE_BYTES    = 32   # bytes of entropy for WebAuthn challenges
