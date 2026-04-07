"""Playwright tests: demo-rp forwards browser Accept-Language as ui_locales."""

import importlib.util
import os
import re
import sys
import threading
import urllib.parse

import pytest
from playwright.sync_api import Browser

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from demo_rp import cfg as demo_rp_cfg  # noqa: E402
AUTHORIZE_RE = re.compile(r"/authorize")


@pytest.fixture(scope="module")
def demo_rp_base_url():
    """Starts the demo-rp Flask server in a background thread."""
    spec = importlib.util.spec_from_file_location(
        "demo_rp_module",
        os.path.join(os.path.dirname(__file__), "..", "demo_rp.py"),
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    from werkzeug.serving import make_server
    server = make_server(demo_rp_cfg.HOST, demo_rp_cfg.PORT, mod.app)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    yield f"http://{demo_rp_cfg.HOST}:{demo_rp_cfg.PORT}"

    server.shutdown()


def _get_authorize_url(browser: Browser, base_url: str, locale: str,
                       ui_locales_value: str = "") -> str:
    """Opens the demo-rp with the given browser locale, submits Verify 2FA,
    and returns the X2FA /authorize URL the demo-rp redirected to."""
    context = browser.new_context(locale=locale)
    page = context.new_page()

    # Abort requests to /authorize so Playwright doesn't actually reach X2FA,
    # but still captures the request URL.
    page.route(AUTHORIZE_RE, lambda route: route.abort())

    page.goto(base_url)
    page.select_option("select[name='ui_locales']", value=ui_locales_value)

    with page.expect_request(AUTHORIZE_RE, timeout=5_000) as req_ctx:
        page.click("button[value='verify']")

    context.close()
    return req_ctx.value.url


@pytest.mark.parametrize("locale,expected_lang", [
    ("de-DE", "de"),
    ("en-US", "en"),
    ("fr-FR", "fr"),
    ("es-ES", "es"),
    ("ja-JP", "ja"),
])
def test_browser_locale_forwarded_as_ui_locales(browser: Browser,
                                                demo_rp_base_url: str,
                                                locale: str,
                                                expected_lang: str):
    """With no explicit dropdown selection the browser locale is forwarded."""
    url = _get_authorize_url(browser, demo_rp_base_url, locale)
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert params.get("ui_locales") == [expected_lang], (
        f"Expected ui_locales={expected_lang!r}, got {params.get('ui_locales')!r}"
    )


def test_explicit_dropdown_overrides_browser_locale(browser: Browser,
                                                    demo_rp_base_url: str):
    """Explicit dropdown selection takes precedence over Accept-Language."""
    url = _get_authorize_url(browser, demo_rp_base_url, locale="de-DE",
                             ui_locales_value="fr")
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert params.get("ui_locales") == ["fr"]


def test_no_ui_locales_when_unsupported_locale(browser: Browser,
                                               demo_rp_base_url: str):
    """An unsupported browser locale results in no ui_locales parameter."""
    url = _get_authorize_url(browser, demo_rp_base_url, locale="xx-XX")
    params = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert "ui_locales" not in params
