# Keyboard focus after deleting a draft

Canceling the confirmation returns focus to **Delete draft**. Confirming deletes that button along with its row, so the dialog moves focus to the **Saved drafts** heading. Its `tabindex="-1"` makes that heading programmatically focusable without adding a tab stop.

The feature in `drafts.js` supplies the opener, deletion action and fallback to the shared `confirmRemoval()` in `confirm-dialog.js`. The primitive uses native `<dialog>` and initially focuses Cancel.

## Run locally or in CI

From this directory, run:

```sh
python check_ui.py
python -m pip install playwright==1.62.0
python -m playwright install chromium
python verify.py
```

On a Linux CI runner that needs browser system libraries, use `python -m playwright install --with-deps chromium`. For a preinstalled Chromium, set `CHROMIUM_PATH` to its executable when running `verify.py`. The test starts a temporary loopback HTTP server. To try the UI yourself, run `python -m http.server --bind 127.0.0.1 8000` here and open http://127.0.0.1:8000.

## What the checks cover

- `check_ui.py` parses `index.html` and `features/**/*.html` for raw dialog start tags. Adding `<dialog>` to feature HTML produces `UI001` with the file, line and replacement API. Pass individual HTML files as arguments to override the default paths. Dynamic JavaScript and framework templates sit outside this example rule's coverage.
- `verify.py` runs the passing source and a deliberately broken HTML fixture through the checker, then drives Chromium using only the keyboard. It checks initial focus, Escape, the Cancel button, and deletion of the focused button's row.
- In a consuming repo, add these commands to its existing required checks. A failure should be visible to the agent locally and to the reviewer on the same change in CI.

## Standard worksheet

- **Primary recommendation** — Strengthen the browser assertion in `verify.py`. A button-only deletion can follow the supported API and pass the HTML lint rule while leaving the draft visible. If focus restoration also failed in callers using the shared primitive correctly, the primitive would need a separate fix.

- **Source and scope** — The delete confirmation for this draft list. The standalone example handles one modal at a time and a synchronous deletion.
- **Observable promise and counterexample** — Escape and Cancel preserve the draft and return focus to its Delete draft button. Confirm removes the draft and focuses Saved drafts. Removing only the button violates the promise even if focus correctly lands on the heading.
- **Owning code and supported path** — Feature code supplies the opener, fallback, and deletion action to `confirmRemoval()`.
- **Executable check and repair** — A raw `<dialog>` in feature HTML triggers `UI001`, which points to the shared primitive and explains which focus targets to pass.
- **Behavioral evidence** — The browser test checks that the row stays visible on both dismissal paths and disappears on confirmation. It also verifies focus after each path.
- **Guidance and judgment** — When adopting the primitive for another list, the feature owner chooses a visible, meaningful fallback.
- **Verification command and CI evidence** — Run `python verify.py` after installing Chromium. In a consuming repo, use the existing CI workflow and link the job result in the PR.
