"""E2E tests for the 2FA method selection screen."""

from playwright.sync_api import Page, expect


class TestSetupChoose:
    def test_page_renders(self, page: Page, goto_with_session, x2fa_server):
        """Method selection screen shows both setup options."""
        goto_with_session("/setup", setup_mode=True)

        expect(page.locator("a[href='/setup/webauthn']")).to_be_visible()
        expect(page.locator("a[href='/totp/setup']")).to_be_visible()

    def test_totp_link_navigates_to_totp_setup(
        self, page: Page, goto_with_session, x2fa_server
    ):
        """Clicking the TOTP option navigates to the TOTP setup page."""
        goto_with_session("/setup", setup_mode=True, user_id="e2e-setup-totp-nav")

        page.click("a[href='/totp/setup']")

        expect(page).to_have_url(f"{x2fa_server}/totp/setup")
        expect(page.locator("img[alt='TOTP QR-Code']")).to_be_visible()
