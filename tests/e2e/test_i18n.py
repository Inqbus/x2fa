from playwright.sync_api import Page, expect
import pytest

# -------------------------
# Existing TOTP/Backup tests
# -------------------------


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


# -------------------------
# New Main App Tests
# -------------------------


class TestCoreRoutesI18n:
    def test_homepage_language_switching(self, page: Page, live_server):
        # Test German locale - use a real route that exists
        page.goto(f"{live_server}/setup?ui_locales=de")
        expect(page.locator("h1")).to_contain_text("Zwei-Faktor-Authentifizierung")
        expect(page.locator("[lang=de]")).to_be_visible()

        # Test French locale
        page.goto(f"{live_server}/setup?ui_locales=fr")
        expect(page.locator("h1")).to_contain_text("Authentification à deux facteurs")
        expect(page.locator("[lang=fr]")).to_be_visible()

    def test_settings_page_language(self, page: Page, live_server):
        page.goto(f"{live_server}/setup/webauthn?ui_locales=es")
        expect(page.locator("h1")).to_contain_text("WebAuthn")
        expect(page.locator("[lang=es]")).to_be_visible()

    def test_about_page_language(self, page: Page, live_server):
        page.goto(f"{live_server}/setup/done?ui_locales=ja")
        expect(page.locator("h1")).to_contain_text("完了")
        expect(page.locator("[lang=ja]")).to_be_visible()

    def test_error_page_language(self, page: Page, live_server):
        page.goto(f"{live_server}/invalid-route?ui_locales=ru")
        expect(page.locator("h1")).to_contain_text("404")
        expect(page.locator("[lang=ru]")).to_be_visible()


# -------------------------
# WebAuthn Specific Tests
# -------------------------


def test_webauthn_cancel_button_i18n(page: Page, live_server):
    # German locale
    page.goto(f"{live_server}/setup/webauthn?ui_locales=de")
    expect(page.locator('button:has-text("Abbrechen")')).to_be_visible()
    expect(page.locator("[lang=de]")).to_be_visible()

    # English locale
    page.goto(f"{live_server}/setup/webauthn?ui_locales=en")
    expect(page.locator('button:has-text("Cancel")')).to_be_visible()
    expect(page.locator("[lang=en]")).to_be_visible()


# -------------------------
# Security Tests
# -------------------------


def test_user_verification_security(page: Page, live_server):
    # Should not reveal user existence
    page.goto(f"{live_server}/verify?username=test")
    # Check that page loads (status 200) by verifying content is present
    expect(page.locator("text=Verification pending...")).to_be_visible()

    # No specific error messages for non-existent users
    page.goto(f"{live_server}/verify?username=nonexistent")
    expect(page.locator("text=Verification pending...")).to_be_visible()
