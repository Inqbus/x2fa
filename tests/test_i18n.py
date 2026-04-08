"""Tests for multilingual rendering via ui_locales."""

import pytest


def _setup_totp(client, user_id: str = "user_test") -> str:
    """Creates a verified TOTP secret and returns the plaintext value."""
    from flask import current_app
    from x2fa.totp_helpers import generate_secret
    from x2fa.services.crypto import CryptoService
    from x2fa.models import TOTPSecret, db

    secret = generate_secret()
    with client.app_context():
        crypto = CryptoService(current_app.config["X2FA_SECRET"])
        secret_encrypted = crypto.encrypt(secret)
        totp_record = db.session.get(TOTPSecret, user_id)
        if totp_record:
            totp_record.secret_encrypted = secret_encrypted
            totp_record.verified = True
            totp_record.last_used_at = None
        else:
            db.session.add(
                TOTPSecret(
                    user_id=user_id,
                    secret_encrypted=secret_encrypted,
                    verified=True,
                )
            )
        db.session.commit()
    return secret


# ---------------------------------------------------------------------------
# Default language (German)
# ---------------------------------------------------------------------------


def test_default_locale_is_german(client):
    """Without ui_locales the UI renders in German."""
    _setup_totp(client)
    client.set_session()  # ui_locales=""
    _, _, body = client.get("/totp/verify")
    assert "Einmalcode".encode() in body


# ---------------------------------------------------------------------------
# ui_locales selects the correct language
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "ui_locales,expected",
    [
        ("en", b"One-time code"),
        ("de", "Einmalcode".encode()),
        ("fr", "Code \u00e0 usage unique".encode()),
        ("es", "C\u00f3digo de un solo uso".encode()),
        ("pt", "C\u00f3digo de uso \u00fanico".encode()),
        ("it", "Codice monouso".encode()),
        ("nl", "Eenmalige code".encode()),
        ("pl", "Jednorazowy kod".encode()),
        (
            "ru",
            "\u041e\u0434\u043d\u043e\u0440\u0430\u0437\u043e\u0432\u044b\u0439 \u043a\u043e\u0434".encode(),
        ),
        ("zh", "\u4e00\u6b21\u6027\u4ee3\u7801".encode()),
        ("ja", "\u30ef\u30f3\u30bf\u30a4\u30e0\u30b3\u30fc\u30c9".encode()),
        ("ko", "\uc77c\ud68c\uc6a9 \ucf54\ub4dc".encode()),
        ("tr", "Tek kullan\u0131ml\u0131k kod".encode()),
        ("sv", "Engångskod".encode()),
        ("cs", "Jednor\u00e1zov\u00fd k\u00f3d".encode()),
        ("hu", "Egyszeri k\u00f3d".encode()),
    ],
)
def test_ui_locales_renders_correct_language(client, ui_locales, expected):
    _setup_totp(client)
    client.set_session(ui_locales=ui_locales)
    _, _, body = client.get("/totp/verify")
    assert expected in body


def test_ui_locales_language_tag_with_region(client):
    """ui_locales='de-CH' should fall back to 'de'."""
    _setup_totp(client)
    client.set_session(ui_locales="de-CH")
    _, _, body = client.get("/totp/verify")
    assert "Einmalcode".encode() in body


def test_ui_locales_unsupported_falls_back_to_german(client):
    """An unsupported language tag falls back to the default (German)."""
    _setup_totp(client)
    client.set_session(ui_locales="xx")
    _, _, body = client.get("/totp/verify")
    assert "Einmalcode".encode() in body


def test_ui_locales_multiple_tags_first_match_wins(client):
    """First supported tag in a space-separated list is used."""
    _setup_totp(client)
    client.set_session(ui_locales="xx fr")  # 'xx' unsupported → 'fr' wins
    _, _, body = client.get("/totp/verify")
    assert "Code \u00e0 usage unique".encode() in body
