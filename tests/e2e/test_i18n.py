import urllib.parse

from playwright.sync_api import Page, expect
import pytest


class TestTOTPVerifyI18n:
    def test_renders_german_with_ui_locales_de(
        self, page: Page, goto_with_session, create_totp, live_server
    ):
        create_totp("e2e-i18n-de")
        goto_with_session("/totp/verify", user_id="e2e-i18n-de", ui_locales="de")
        expect(page.locator("label[for='code']")).to_contain_text("Einmalcode")

    def test_renders_english_with_ui_locales_en(
        self, page: Page, goto_with_session, create_totp, live_server
    ):
        create_totp("e2e-i18n-en")
        goto_with_session("/totp/verify", user_id="e2e-i18n-en", ui_locales="en")
        expect(page.locator("label[for='code']")).to_contain_text("One-time code")

    def test_renders_french_with_ui_locales_fr(
        self, page: Page, goto_with_session, create_totp, live_server
    ):
        create_totp("e2e-i18n-fr")
        goto_with_session("/totp/verify", user_id="e2e-i18n-fr", ui_locales="fr")
        expect(page.locator("label[for='code']")).to_contain_text("Code à usage unique")

    def test_unsupported_locale_falls_back_to_german(
        self, page: Page, goto_with_session, create_totp, live_server
    ):
        create_totp("e2e-i18n-xx")
        goto_with_session("/totp/verify", user_id="e2e-i18n-xx", ui_locales="xx")
        expect(page.locator("label[for='code']")).to_contain_text("Einmalcode")


class TestBackupVerifyI18n:
    def test_renders_german_with_ui_locales_de(
        self, page: Page, goto_with_session, live_server
    ):
        goto_with_session("/backup/verify", ui_locales="de")
        expect(page.locator("h1")).to_contain_text("Backup-Code")

    def test_renders_english_with_ui_locales_en(
        self, page: Page, goto_with_session, live_server
    ):
        goto_with_session("/backup/verify", ui_locales="en")
        expect(page.locator("h1")).to_contain_text("backup code")


class TestCoreRoutesI18n:
    def test_homepage_language_switching(
        self, page: Page, goto_with_session, live_server
    ):
        """Setup page renders in the language specified by ui_locales."""
        goto_with_session("/setup", setup_mode=True, ui_locales="de")
        expect(page.locator("h1")).to_contain_text("Zwei-Faktor-Authentifizierung")
        expect(page.locator("[lang=de]")).to_be_visible()

        goto_with_session("/setup", setup_mode=True, ui_locales="fr")
        expect(page.locator("h1")).to_contain_text("deux facteurs")
        expect(page.locator("[lang=fr]")).to_be_visible()

    def test_settings_page_language(
        self, page: Page, goto_with_session, live_server
    ):
        """WebAuthn setup page renders in Spanish."""
        goto_with_session("/setup/webauthn", setup_mode=True, ui_locales="es")
        expect(page.locator("h1")).to_contain_text("Configurar")
        expect(page.locator("[lang=es]")).to_be_visible()

    def test_about_page_language(
        self, page: Page, goto_with_session, live_server
    ):
        """Setup page renders in Japanese."""
        goto_with_session("/setup", setup_mode=True, ui_locales="ja")
        expect(page.locator("h1")).to_contain_text("二要素認証")
        expect(page.locator("[lang=ja]")).to_be_visible()

    def test_error_page_language(
        self, page: Page, goto_with_session, live_server
    ):
        """404 error page renders in the language from the active session."""
        goto_with_session("/nonexistent-page", ui_locales="ru")
        expect(page.locator("h1")).to_contain_text("404")
        expect(page.locator("[lang=ru]")).to_be_visible()


def test_webauthn_cancel_button_i18n(
    page: Page, goto_with_session, live_server
):
    """Cancel button on WebAuthn setup page is translated (button is hidden until WebAuthn starts)."""
    goto_with_session("/setup/webauthn", setup_mode=True, ui_locales="de")
    expect(page.locator("#cancel-btn")).to_have_text("Abbrechen")
    expect(page.locator("[lang=de]")).to_be_visible()

    goto_with_session("/setup/webauthn", setup_mode=True, ui_locales="en")
    expect(page.locator("#cancel-btn")).to_have_text("Cancel")
    expect(page.locator("[lang=en]")).to_be_visible()


def test_user_verification_security(
    page: Page, goto_with_session, capture_callback, live_server
):
    """Users without 2FA get an OIDC access_denied error, not a user-specific message."""
    url = capture_callback(
        lambda: goto_with_session("/verify", user_id="e2e-no-2fa-user")
    )
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert params.get("error") == ["access_denied"]
