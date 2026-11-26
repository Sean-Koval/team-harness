"""Verify the UI001 diagnostic and keyboard behavior in a real Chromium browser."""
import os
import subprocess
import sys
import tempfile
import threading
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parent


def check_lint():
    check = [sys.executable, str(ROOT / "check_ui.py")]
    subprocess.run(check, check=True)
    with tempfile.TemporaryDirectory() as directory:
        bad = Path(directory) / "draft.html"
        bad.write_text("<main>\n  <dialog>Delete?</dialog>\n</main>", encoding="utf-8")
        result = subprocess.run([*check, str(bad)], capture_output=True, text=True)
        assert result.returncode == 1 and "2:3 UI001" in result.stderr, result.stderr
        assert "confirmRemoval()" in result.stderr, result.stderr


def check_keyboard(page, url):
    page.goto(url)
    draft = page.get_by_role("listitem").filter(has_text="Quarterly update")
    opener = draft.get_by_role("button", name="Delete draft", exact=True)
    dialog = page.get_by_role("dialog", name="Delete Quarterly update?")
    expect(draft).to_be_visible()
    page.keyboard.press("Tab")
    expect(opener).to_be_focused()
    for key in ("Escape", "Enter"):
        page.keyboard.press("Enter")
        expect(dialog.get_by_role("button", name="Cancel")).to_be_focused()
        page.keyboard.press(key)
        expect(dialog).to_have_count(0)
        expect(draft).to_be_visible()
        expect(opener).to_be_focused()
    page.keyboard.press("Enter")
    expect(dialog.get_by_role("button", name="Cancel")).to_be_focused()
    page.keyboard.press("Tab")
    expect(dialog.get_by_role("button", name="Delete", exact=True)).to_be_focused()
    page.keyboard.press("Enter")
    expect(draft).to_have_count(0)
    expect(dialog).to_have_count(0)
    expect(page.get_by_role("heading", name="Saved drafts")).to_be_focused()


if __name__ == "__main__":
    check_lint()
    handler = partial(SimpleHTTPRequestHandler, directory=str(ROOT))
    with ThreadingHTTPServer(("127.0.0.1", 0), handler) as server, sync_playwright() as playwright:
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            browser = playwright.chromium.launch(executable_path=os.getenv("CHROMIUM_PATH"))
            try:
                check_keyboard(browser.new_page(), f"http://127.0.0.1:{server.server_port}")
            finally:
                browser.close()
        finally:
            server.shutdown()
            worker.join()
    print("Passed UI001 positive and negative cases and all three Chromium keyboard paths.")
