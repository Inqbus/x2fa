# Audit action strings
ACTION_SETUP  = "setup"
ACTION_VERIFY = "verify"
ACTION_FAIL   = "fail"

# Audit method strings
METHOD_WEBAUTHN_PLATFORM = "webauthn_platform"
METHOD_WEBAUTHN_ROAMING  = "webauthn_roaming"
METHOD_TOTP              = "totp"
METHOD_BACKUP            = "backup"

# Cryptography — not admin-tunable, fixed by design
BCRYPT_ROUNDS      = 12   # bcrypt cost factor for backup-code hashes
BACKUP_CODES_COUNT = 10   # number of single-use backup codes generated per registration
CHALLENGE_BYTES    = 32   # bytes of entropy for WebAuthn challenges
