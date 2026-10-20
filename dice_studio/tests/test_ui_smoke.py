"""Optional end-to-end UI test in headless Chromium (skipped if Playwright is not installed).

    pip install playwright && python -m playwright install chromium
    set DICE_UI_CHROMIUM=<path to chrome> to use an existing browser binary.
"""
import os
import threading

import pytest

pw = pytest.importorskip("playwright.sync_api")


@pytest.fixture(scope="module")
def server(tmp_path_factory):
    from http.server import ThreadingHTTPServer

    from dicestudio.server import App, make_handler

    app = App(tmp_path_factory.mktemp("uiws"))
    srv = ThreadingHTTPServer(("127.0.0.1", 0), make_handler(app))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_address[1]}/", app
    srv.shutdown()


def test_ui_generates_and_validates(server):
    url, app = server
    with pw.sync_playwright() as p:
        kw = {"args": ["--use-gl=angle", "--use-angle=swiftshader", "--enable-unsafe-swiftshader"]}
        if os.environ.get("DICE_UI_CHROMIUM"):
            kw["executable_path"] = os.environ["DICE_UI_CHROMIUM"]
        try:
            browser = p.chromium.launch(**kw)
        except Exception as exc:  # browser binary not installed
            pytest.skip(f"no Chromium available: {exc}")
        page = browser.new_page(viewport={"width": 1400, "height": 850})
        errors = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        page.goto(url)

        def wait_all(timeout=180000):
            try:
                page.wait_for_function("document.querySelectorAll('.dot.ok, .dot.warn').length == 7", timeout=timeout)
            except Exception:
                raise AssertionError("dice did not finish: " + page.inner_text("#messages") + " | " + str(errors))

        wait_all()
        # select a die, regenerate only it, undo
        page.click("#card-d12")
        page.click("text=Regenerate this die")
        page.wait_for_timeout(500)
        wait_all()
        page.click("#btn-undo")
        # every view mode renders without errors
        for mode in ["wireframe", "validation", "blank", "cutaway", "blankonly", "compare", "rendered"]:
            page.select_option("#view-mode", mode)
            page.wait_for_timeout(300)
        page.click("#btn-validate")
        page.wait_for_selector("text=All meshes valid", timeout=180000)
        assert not errors, errors
        browser.close()
