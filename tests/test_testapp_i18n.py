"""Playwright tests: testapp forwards browser Accept-Language as ui_locales."""

import importlib.util
import os
import re
import sys
import threading
import urllib.parse

import pytest
from playwright.sync_api import Browser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

_TESTAPP_HOST = "127.0.0.1"
_TESTAPP_PORT = 5099
_AUTHORIZE_RE = re.compile(r"/authorize")


@pytest.fixture(scope="module")
def testapp_base_url():
    """Starts the testapp Flask server in a background thread."""
    spec = importlib.util.spec_from_file_location(
        "testapp_module",
        os.path.join(os.path.dirname(__file__), "..", "testapp.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from werkzeug.serving import make_server
    server = make_server(_TESTAPP_HOST, _TESTAPP_PORT, mod.app)
    t = threading.Thread(target=server.serve_forever, daemon=True)
    t.start()

    yield f"http://{_TESTAPP_HOST}:{_TESTAPP_PORT}"

    server.shutdown()


def _get_authorize_url(browser: Browser, base_url: str, locale: str,
                       ui_locales_value: str = "") -> str:
    """Opens the testapp with the given browser locale, submits Verify 2FA,
    and returns the X2FA /authorize URL the testapp redirected to."""
    context = browser.new_context(locale=locale)
    page = context.new_page()

    # Abort requests to /authorize so Playwright doesn't actually reach X2FA,
    # but still captures the request URL.
    page.route(_AUTHORIZE_RE, lambda route: route.abort())

    page.goto(base_url)
    page.select_option("select[name='ui_locales']", value=ui_locales_value)

    with page.expect_request(_AUTHORIZE_RE, timeout=5_000) as req_ctx:
        page.click("button[value='verify']")

    url = req_ctx.value.url
    context.close()
    return url


@pytest.mark.parametrize("locale,expected_lang", [
    ("de-DE", "de"),
    ("en-US", "en"),
    ("fr-FR", "fr"),
    ("es-ES", "es"),
    ("ja-JP", "ja"),
])
def test_browser_locale_forwarded_as_ui_locales(browser: Browser,
                                                testapp_base_url: str,
                                                locale: str,
                                                expected_lang: str):
    """With no explicit dropdown selection the browser locale is forwarded."""
    url = _get_authorize_url(browser, testapp_base_url, locale)
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert params.get("ui_locales") == [expected_lang], (
        f"Expected ui_locales={expected_lang!r}, got {params.get('ui_locales')!r}"
    )


def test_explicit_dropdown_overrides_browser_locale(browser: Browser,
                                                    testapp_base_url: str):
    """Explicit dropdown selection takes precedence over Accept-Language."""
    url = _get_authorize_url(browser, testapp_base_url, locale="de-DE",
                             ui_locales_value="fr")
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert params.get("ui_locales") == ["fr"]


def test_no_ui_locales_when_unsupported_locale(browser: Browser,
                                               testapp_base_url: str):
    """An unsupported browser locale results in no ui_locales parameter."""
    url = _get_authorize_url(browser, testapp_base_url, locale="xx-XX")
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert "ui_locales" not in params
