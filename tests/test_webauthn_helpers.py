"""Tests for webauthn_helpers — registration and authentication option builders.

These tests verify that build_registration_options_json and
build_authentication_options_json correctly read config from
current_app and produce valid WebAuthn JSON output.
"""

import json
import os
import pathlib

import pytest

from x2fa import paths
from x2fa.app import create_app
from x2fa.helpers import webauthn_helpers


# ── Test config templates ─────────────────────────────────────────────────────

_X2FA_CONFIG = """\
[default]
HOST = "127.0.0.1"
PORT = 5000
CALLBACK_PORT = 19999
DOMAIN = "test.example.com"
ORIGIN = "https://test.example.com"
NAME = "X2FA Test"

[testing]
HOST = "127.0.0.1"
PORT = 5098
DOMAIN = "localhost"
ORIGIN = "https://localhost"

[production]
DOMAIN = "test.example.com"
ORIGIN = "https://test.example.com"
NAME = "X2FA Test"
TESTING = false
"""

_SECURITY_CONFIG = """\
[default]
SECRET_KEY = "00000000000000000000000000000000"
SECRET_SALT = "1111111111111111"

[testing]
SECRET_KEY = "testing-secret-key"
SESSION_COOKIE_SECURE = false
SESSION_COOKIE_SAMESITE = false
WTF_CSRF_ENABLED = true
CLIENT_ID = "testing-client"
CLIENT_SECRET = "testing-secret"

[production]
SECRET_KEY = "00000000000000000000000000000000"
SECRET_SALT = "1111111111111111"
SESSION_COOKIE_SECURE = true
SESSION_COOKIE_HTTPONLY = true
SESSION_COOKIE_SAMESITE = "Lax"
PERMANENT_SESSION_LIFETIME = 600
"""

_DB_CONFIG = """\
[default]
SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

[testing]
SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"

[production]
SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
"""

_RATELIMIT_CONFIG = """\
[default]
RATELIMIT_AUTHORIZE = "10/minute"
RATELIMIT_TOKEN = "10/minute"
RATE_LIMIT_SETUP_COMPLETE = "5/minute"
RATE_LIMIT_WEBAUTHN_VERIFY = "10/minute"
RATE_LIMIT_BACKUP_VERIFY = "5/minute"
RATE_LIMIT_TOTP_SETUP = "10/minute"
RATE_LIMIT_TOTP_VERIFY = "10/minute"
CHALLENGE_TTL_MINUTES = 5
REDIS_URL = ""

[testing]
RATELIMIT_AUTHORIZE = "10/minute"
RATELIMIT_TOKEN = "10/minute"
RATE_LIMIT_SETUP_COMPLETE = "5/minute"
RATE_LIMIT_WEBAUTHN_VERIFY = "10/minute"
RATE_LIMIT_BACKUP_VERIFY = "5/minute"
RATE_LIMIT_TOTP_SETUP = "10/minute"
RATE_LIMIT_TOTP_VERIFY = "10/minute"
CHALLENGE_TTL_MINUTES = 5
REDIS_URL = ""

[production]
RATELIMIT_AUTHORIZE = "10/minute"
RATELIMIT_TOKEN = "10/minute"
RATE_LIMIT_SETUP_COMPLETE = "5/minute"
RATE_LIMIT_WEBAUTHN_VERIFY = "10/minute"
RATE_LIMIT_BACKUP_VERIFY = "5/minute"
RATE_LIMIT_TOTP_SETUP = "10/minute"
RATE_LIMIT_TOTP_VERIFY = "10/minute"
CHALLENGE_TTL_MINUTES = 5
REDIS_URL = ""
"""

_BABEL_CONFIG = """\
[default]
BABEL_DEFAULT_LOCALE = "de"
BABEL_SUPPORTED_LOCALES = ["de", "en"]
BABEL_TRANSLATION_DIRECTORIES = "../translations"
"""


def _write_test_config(tmp_path: pathlib.Path) -> None:
    """Write minimal X2FA config files into tmp_path/.config/x2fa/."""
    config_dir = tmp_path / ".config" / "x2fa"
    config_dir.mkdir(parents=True)

    (config_dir / "x2fa_config.toml").write_text(_X2FA_CONFIG)
    (config_dir / "security_config.toml").write_text(_SECURITY_CONFIG)
    (config_dir / "db_config.toml").write_text(_DB_CONFIG)
    (config_dir / "ratelimit_config.toml").write_text(_RATELIMIT_CONFIG)
    (config_dir / "babel_config.toml").write_text(_BABEL_CONFIG)


@pytest.fixture(autouse=True)
def _test_config(tmp_path):
    """Provide a complete X2FA config in tmp_path for all tests in this module."""
    _write_test_config(tmp_path)
    old_home = os.environ.get("X2FA_HOME")
    os.environ["X2FA_HOME"] = str(tmp_path)
    yield tmp_path
    if old_home:
        os.environ["X2FA_HOME"] = old_home
    else:
        os.environ.pop("X2FA_HOME", None)


class TestBuildRegistrationOptionsJson:
    """Tests for build_registration_options_json()."""

    def test_returns_valid_json_string(self, _test_config):
        """Returns a parseable JSON string with WebAuthn registration fields."""
        with create_app().test_request_context():
            result = webauthn_helpers.build_registration_options_json(
                user_id="test-user",
                challenge=b"\x00" * 32,
            )
        data = json.loads(result)
        # py_webauthn 3.x outputs flat JSON (no "publicKey" wrapper)
        assert "challenge" in data
        assert "rp" in data
        assert "user" in data

    def test_includes_rp_id_from_config(self, _test_config):
        """rp.id matches current_app.config.x2fa.DOMAIN."""
        with create_app().test_request_context():
            result = webauthn_helpers.build_registration_options_json(
                user_id="test-user",
                challenge=b"\x00" * 32,
            )
        data = json.loads(result)
        assert data["rp"]["id"] == "test.example.com"

    def test_includes_rp_name_from_config(self, _test_config):
        """rp.name matches current_app.config.x2fa.NAME."""
        with create_app().test_request_context():
            result = webauthn_helpers.build_registration_options_json(
                user_id="test-user",
                challenge=b"\x00" * 32,
            )
        data = json.loads(result)
        assert data["rp"]["name"] == "X2FA Test"

    def test_includes_user_id_and_name(self, _test_config):
        """user.id and user.name are set from arguments."""
        import base64
        with create_app().test_request_context():
            result = webauthn_helpers.build_registration_options_json(
                user_id="alice@example.com",
                challenge=b"\x00" * 32,
            )
        data = json.loads(result)
        user = data["user"]
        expected_id = base64.urlsafe_b64encode("alice@example.com".encode()).rstrip(b"=").decode()
        assert user["id"] == expected_id
        assert user["name"] == "alice@example.com"
        assert user["displayName"] == "alice@example.com"

    def test_includes_challenge(self, _test_config):
        """challenge bytes are base64url-encoded in the output."""
        challenge = b"\xde\xad\xbe\xef" * 8
        with create_app().test_request_context():
            result = webauthn_helpers.build_registration_options_json(
                user_id="test-user",
                challenge=challenge,
            )
        data = json.loads(result)
        import base64
        expected = base64.urlsafe_b64encode(challenge).rstrip(b"=").decode()
        assert data["challenge"] == expected

    def test_sets_resident_key_preferred(self, _test_config):
        """residentKey is set to 'preferred' (passkey-friendly)."""
        with create_app().test_request_context():
            result = webauthn_helpers.build_registration_options_json(
                user_id="test-user",
                challenge=b"\x00" * 32,
            )
        data = json.loads(result)
        assert data["authenticatorSelection"]["residentKey"] == "preferred"

    def test_sets_user_verification_required(self, _test_config):
        """userVerification is set to 'required'."""
        with create_app().test_request_context():
            result = webauthn_helpers.build_registration_options_json(
                user_id="test-user",
                challenge=b"\x00" * 32,
            )
        data = json.loads(result)
        assert data["authenticatorSelection"]["userVerification"] == "required"

    def test_requires_bytes_challenge(self, _test_config):
        """challenge must be bytes, not str."""
        with create_app().test_request_context():
            with pytest.raises(TypeError):
                webauthn_helpers.build_registration_options_json(
                    user_id="test-user",
                    challenge="not-bytes",
                )


class TestBuildAuthenticationOptionsJson:
    """Tests for build_authentication_options_json()."""

    def test_returns_valid_json_string(self, _test_config):
        """Returns a parseable JSON string."""
        cred_id = b"\x01\x02\x03"
        with create_app().test_request_context():
            result = webauthn_helpers.build_authentication_options_json(
                challenge=b"\x00" * 32,
                credential_ids=[cred_id],
            )
        data = json.loads(result)
        assert "allowCredentials" in data

    def test_includes_rp_id_from_config(self, _test_config):
        """rpId matches current_app.config.x2fa.DOMAIN."""
        cred_id = b"\x01\x02\x03"
        with create_app().test_request_context():
            result = webauthn_helpers.build_authentication_options_json(
                challenge=b"\x00" * 32,
                credential_ids=[cred_id],
            )
        data = json.loads(result)
        assert data["rpId"] == "test.example.com"

    def test_includes_credential_ids(self, _test_config):
        """allowCredentials contains the provided credential IDs (base64url-encoded)."""
        import base64
        cred_id = b"\x01\x02\x03\x04"
        with create_app().test_request_context():
            result = webauthn_helpers.build_authentication_options_json(
                challenge=b"\x00" * 32,
                credential_ids=[cred_id],
            )
        data = json.loads(result)
        allow = data["allowCredentials"]
        assert len(allow) == 1
        expected_id = base64.urlsafe_b64encode(cred_id).rstrip(b"=").decode()
        assert allow[0]["id"] == expected_id

    def test_handles_multiple_credentials(self, _test_config):
        """Multiple credential IDs are all included."""
        cred_ids = [b"\x01" * 16, b"\x02" * 16, b"\x03" * 16]
        with create_app().test_request_context():
            result = webauthn_helpers.build_authentication_options_json(
                challenge=b"\x00" * 32,
                credential_ids=cred_ids,
            )
        data = json.loads(result)
        allow = data["allowCredentials"]
        assert len(allow) == 3

    def test_handles_empty_credential_list(self, _test_config):
        """Empty credential list produces empty allowCredentials."""
        with create_app().test_request_context():
            result = webauthn_helpers.build_authentication_options_json(
                challenge=b"\x00" * 32,
                credential_ids=[],
            )
        data = json.loads(result)
        assert data["allowCredentials"] == []

    def test_handles_transports(self, _test_config):
        """Transports are passed through to allowCredentials."""
        cred_id = b"\x01" * 16
        transports = [["usb", "nfc"]]
        with create_app().test_request_context():
            result = webauthn_helpers.build_authentication_options_json(
                challenge=b"\x00" * 32,
                credential_ids=[cred_id],
                transports=transports,
            )
        data = json.loads(result)
        allow = data["allowCredentials"][0]
        assert allow["transports"] == ["usb", "nfc"]

    def test_handles_none_transports(self, _test_config):
        """None transports means no transports field."""
        cred_id = b"\x01" * 16
        with create_app().test_request_context():
            result = webauthn_helpers.build_authentication_options_json(
                challenge=b"\x00" * 32,
                credential_ids=[cred_id],
                transports=None,
            )
        data = json.loads(result)
        allow = data["allowCredentials"][0]
        assert "transports" not in allow

    def test_handles_missing_transports_for_credential(self, _test_config):
        """Missing transport entry for a credential means no transports."""
        cred_ids = [b"\x01" * 16, b"\x02" * 16]
        transports = [["usb"]]  # only one entry for two credentials
        with create_app().test_request_context():
            result = webauthn_helpers.build_authentication_options_json(
                challenge=b"\x00" * 32,
                credential_ids=cred_ids,
                transports=transports,
            )
        data = json.loads(result)
        allow = data["allowCredentials"]
        assert allow[0]["transports"] == ["usb"]
        assert "transports" not in allow[1]

    def test_invalid_transport_value_is_ignored(self, _test_config):
        """Invalid transport string values are silently skipped."""
        cred_id = b"\x01" * 16
        transports = [["usb", "invalid_transport_xyz", "nfc"]]
        with create_app().test_request_context():
            result = webauthn_helpers.build_authentication_options_json(
                challenge=b"\x00" * 32,
                credential_ids=[cred_id],
                transports=transports,
            )
        data = json.loads(result)
        allow = data["allowCredentials"][0]
        assert allow["transports"] == ["usb", "nfc"]

    def test_challenge_is_base64url_encoded(self, _test_config):
        """Challenge bytes are base64url-encoded."""
        challenge = b"\xca\xfe\xba\xbe" * 8
        with create_app().test_request_context():
            result = webauthn_helpers.build_authentication_options_json(
                challenge=challenge,
                credential_ids=[],
            )
        data = json.loads(result)
        import base64
        expected = base64.urlsafe_b64encode(challenge).rstrip(b"=").decode()
        assert data["challenge"] == expected


class TestWebauthnHelpersNoGlobalApp:
    """Verify that webauthn_helpers no longer depends on a global 'app' variable.

    The module should only use current_app from Flask, which is a thread-local
    proxy that resolves to the correct app in the current request context.
    """

    def test_module_has_no_global_app(self):
        """The module must not define or reference a global 'app' variable."""
        import x2fa.helpers.webauthn_helpers as mod
        # Check that 'app' is not a module-level name
        assert "app" not in dir(mod) or not hasattr(mod, "app")

    def test_uses_current_app_not_global(self):
        """All config access goes through current_app, not a global."""
        import inspect
        source = inspect.getsource(webauthn_helpers)
        # Should contain current_app references
        assert "current_app" in source
        # Should NOT contain bare 'app.' references (which would be globals)
        # We check for patterns like 'app.' that are NOT part of 'current_app.'
        import re
        # Find all 'app.' occurrences that are not preceded by 'current_'
        matches = re.findall(r'(?<!current_)app\.', source)
        assert len(matches) == 0, (
            f"Found bare 'app.' references (should use current_app): {matches}"
        )