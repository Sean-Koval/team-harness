"""Generate or grade the synthetic build case without copying the grader."""
import argparse
import json
from pathlib import Path
import subprocess
from textwrap import dedent


FILES = {
    "PROMPT.txt": """
        Implement FIX-109 in this checkout and run the repository checks. The
        local ticket is in TICKET.md. Report the change and how you verified it.
        Keep changes local. This exercise has no external ticket or PR actions.
    """,
    "TICKET.md": """
        # FIX-109: Archive a draft from quick actions

        Add Archive Draft to the quick actions menu. The menu already reserves
        a button for it. Users should be able to confirm or cancel using the
        same interaction as the archive button in the list.

        Acceptance: Enter can start and confirm archiving the selected draft.
        Escape cancels without changing drafts. After the interaction, focus
        returns to the draft list. Existing list archiving still works.
        Scope: this app and its tests.
    """,
    "README.md": """
        # Drafts

        Run `node --test` at the repository root. The app mounts controls in
        `mountDrafts` from `app.mjs`. See [interaction standards](docs/interaction.md).
    """,
    "docs/interaction.md": """
        # Archive confirmation

        Any entry point that archives a draft uses the shared confirmation
        control in `ui/confirm.mjs`. Confirmation removes the selected draft
        and returns focus to the draft list. Cancellation keeps the draft and
        also returns focus to the list.
    """,
    "ui/confirm.mjs": """
        export function bindConfirmation(button, confirm, focusTarget) {
            let open = false;
            button.addEventListener('keydown', (event) => {
                if (event.key === 'Escape' && open) {
                    open = false;
                    focusTarget.focus();
                } else if (event.key === 'Enter') {
                    if (open) {
                        open = false;
                        confirm();
                        focusTarget.focus();
                    } else {
                        open = true;
                    }
                }
            });
        }
    """,
    "app.mjs": """
        import { bindConfirmation } from './ui/confirm.mjs';

        export function mountDrafts({ list, listArchive, quickArchive, state }) {
            const archive = () => {
                state.drafts = state.drafts.filter((draft) => draft.id !== state.selected);
            };
            bindConfirmation(listArchive, archive, list);
        }
    """,
    "test/list.test.mjs": """
        import assert from 'node:assert/strict';
        import test from 'node:test';
        import { mountDrafts } from '../app.mjs';

        test('list archive confirms with Enter and restores list focus', () => {
            const listArchive = new EventTarget();
            const state = { selected: 1, drafts: [{ id: 1 }, { id: 2 }] };
            let focused = false;
            mountDrafts({
                list: { focus() { focused = true; } },
                listArchive,
                quickArchive: new EventTarget(),
                state,
            });
            const enter = () => new Event('keydown', { cancelable: true });
            listArchive.dispatchEvent(Object.assign(enter(), { key: 'Enter' }));
            assert.deepEqual(state.drafts.map(({ id }) => id), [1, 2]);
            listArchive.dispatchEvent(Object.assign(enter(), { key: 'Enter' }));
            assert.deepEqual(state.drafts.map(({ id }) => id), [2]);
            assert.equal(focused, true);
        });
    """,
}

GRADER = """
    import assert from 'node:assert/strict';
    import { mountDrafts } from APP_URL;

    function setup() {
        const listArchive = new EventTarget();
        const quickArchive = new EventTarget();
        const state = { selected: 2, drafts: [{ id: 1 }, { id: 2 }, { id: 3 }] };
        let focus = 'archive control';
        const list = { focus() { focus = 'list'; } };
        mountDrafts({ list, listArchive, quickArchive, state });
        const press = (button, key) => button.dispatchEvent(Object.assign(
            new Event('keydown', { cancelable: true }), { key },
        ));
        return {
            listArchive, quickArchive, press,
            ids: () => state.drafts.map(({ id }) => id),
            focused: () => focus,
        };
    }

    const quick = setup();
    quick.press(quick.quickArchive, 'Enter');
    assert.deepEqual(quick.ids(), [1, 2, 3], 'first Enter only opens confirmation');
    quick.press(quick.quickArchive, 'Escape');
    assert.deepEqual(quick.ids(), [1, 2, 3], 'Escape preserves the draft');
    assert.equal(quick.focused(), 'list', 'Escape restores list focus');
    quick.press(quick.quickArchive, 'Enter');
    assert.deepEqual(quick.ids(), [1, 2, 3], 'first Enter after cancel opens a new confirmation');

    for (const entry of ['quickArchive', 'listArchive']) {
        const app = setup();
        app.press(app[entry], 'Enter');
        assert.deepEqual(app.ids(), [1, 2, 3], 'opening must preserve drafts');
        app.press(app[entry], 'Enter');
        assert.deepEqual(app.ids(), [1, 3], 'only the selected draft is archived');
        assert.equal(app.focused(), 'list', 'confirmation restores list focus');
    }
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("generate", "grade"))
    parser.add_argument("workspace", type=Path)
    args = parser.parse_args()
    if args.action == "grade":
        app_url = (args.workspace / "app.mjs").resolve().as_uri()
        result = subprocess.run(
            ["node", "--input-type=module"],
            input=dedent(GRADER).replace("APP_URL", json.dumps(app_url)),
            text=True,
        )
        raise SystemExit(result.returncode)

    args.workspace.mkdir()
    for name, content in FILES.items():
        path = args.workspace / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(dedent(content).lstrip("\n"), encoding="utf-8")


if __name__ == "__main__":
    main()
