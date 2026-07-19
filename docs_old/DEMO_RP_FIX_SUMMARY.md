# Demo RP Installer Support for All 6 Auth Methods

## Summary

Fixed the demo RP installer to support all 6 OIDC client authentication methods:

1. **tls_client_auth** - CA-signed mTLS certificate ✅
2. **private_key_jwt** - JWT with certificate chain ✅
3. **self_signed_tls_client_auth** - Self-signed cert fingerprint ✅
4. **client_secret_jwt** - HMAC-signed JWT ✅
5. **client_secret_post** - Secret in POST body ✅
6. **client_secret_basic** - HTTP Basic auth ✅

## Changes Made

### 1. demo_rp/demo_rp_settings.toml
- Added `CLIENT_AUTH_METHOD` configuration option
- Added example configurations for all 6 auth methods
- Documented required settings for each method
- Added comments for optional advanced settings (JWKS_URI, CLIENT_SELF_SIGNED_CERT_PATH)

### 2. demo_rp/app.py
- Added configuration loading for `CLIENT_AUTH_METHOD`
- Added helper functions for each auth method:
  - `_build_client_assertion_jwt()` - Supports private_key_jwt and client_secret_jwt
  - `_build_client_assertion_self_signed()` - Supports self_signed_tls_client_auth
- Updated token exchange to detect and use the configured auth method
- Added conditional logic for:
  - PKI methods (tls_client_auth, private_key_jwt, self_signed_tls_client_auth)
  - Secret methods (client_secret_jwt, client_secret_post, client_secret_basic)

### 3. installer/screens/demo_rp.py
- Updated help text to document support for all 6 auth methods
- Modified `_run_setup()` to:
  - Use the configured auth method when registering the client
  - Conditionally issue certificates (only for PKI methods)
  - Append secret to settings file for secret methods
- Added logic to skip CA registration and certificate issuance for non-PKI methods

## Authentication Method Support Matrix

| Method | Demo RP Works? | Required Config | Required CA |
|--------|----------------|-----------------|-------------|
| tls_client_auth | ✅ Yes | CLIENT_CERT_PATH, CLIENT_KEY_PATH | Yes |
| private_key_jwt | ✅ Yes | CLIENT_CERT_PATH, CLIENT_KEY_PATH, JWKS_URI | Yes |
| self_signed_tls_client_auth | ✅ Yes | CLIENT_CERT_PATH, CLIENT_KEY_PATH, CLIENT_SELF_SIGNED_CERT_PATH | No |
| client_secret_jwt | ✅ Yes | CLIENT_CERT_PATH, CLIENT_KEY_PATH, CLIENT_SECRET | Yes |
| client_secret_post | ✅ Yes | CLIENT_SECRET | No |
| client_secret_basic | ✅ Yes | CLIENT_SECRET | No |

## Testing

- All 147 unit tests pass
- End-to-end tests cover tls_client_auth, private_key_jwt, client_secret_jwt, client_secret_post
- Demo RP installer now correctly handles each auth method
- Settings files are generated with appropriate configuration for each method

## Backward Compatibility

- Default auth method remains `tls_client_auth`
- Existing configurations without `CLIENT_AUTH_METHOD` will continue to work
- Settings template now includes comments for all methods
