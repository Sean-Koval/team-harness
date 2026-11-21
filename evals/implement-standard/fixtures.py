"""Materialize independent, synthetic routing-eval workspaces."""
from argparse import ArgumentParser
from pathlib import Path
from textwrap import dedent

TASK = """\
Inspect this repository and recommend where we should fix the reported problem.
Start with your recommendation and explain what you verified. Describe how we
could verify the fix. This is an advisory request. Leave the files as they are.

"""

CASES = {
    "01": (
        "Team export must produce a valid header-only CSV for an empty team. "
        "The team export job errors before downloading. Where should we fix this?",
        {
            "README.md": "Supported exports use export_csv(rows) from shared/exports.py.\n",
            "jobs/team.py": "from shared.exports import export_csv\n\n\ndef download(team_rows):\n    return export_csv(team_rows)\n",
            "shared/exports.py": '''
                from csv import DictWriter
                from io import StringIO

                def export_csv(rows):
                    output = StringIO()
                    writer = DictWriter(output, fieldnames=rows[0].keys())
                    writer.writeheader()
                    writer.writerows(rows)
                    return output.getvalue()
            ''',
            "docs/team-export.md": "Columns are name and email, in that order.\n",
        },
    ),
    "02": (
        "After a user confirms deletion of a draft, focus should return to the draft list. "
        "The new toolbar fails this check. Where should we fix this?",
        {
            "README.md": "Use ui/dialog.confirmDelete for draft deletion. The panel primitive is also supported inside ui/ for non-delete controls.\n",
            "ui/dialog.js": '''
                import { openPanel } from './panel.js';
                export function confirmDelete(remove, list) {
                    return openPanel(() => {
                        remove();
                        list.focus();
                    });
                }
            ''',
            "ui/panel.js": "export function openPanel(onConfirm) { return { confirm: onConfirm }; }\n",
            "ui/preferences.js": "import { openPanel } from './panel.js';\nexport const editPreferences = (save) => openPanel(save);\n",
            "drafts/list.js": "import { confirmDelete } from '../ui/dialog.js';\nexport const deleteFromList = (remove, list) => confirmDelete(remove, list);\n",
            "drafts/toolbar.js": "import { openPanel } from '../ui/panel.js';\nexport const deleteFromToolbar = (remove) => openPanel(remove);\n",
        },
    ),
    "03": (
        "New services generated this week report that an empty team export crashes. "
        "An existing reference service handles it. Where should we fix this?",
        {
            "README.md": "Generate a service with python generate.py <destination>. The reference service uses the same export API.\n",
            "generate.py": '''
                from pathlib import Path
                from shutil import copyfile
                import sys

                root = Path(__file__).parent
                destination = Path(sys.argv[1])
                destination.mkdir()
                copyfile(root / 'service-template/requirements.txt', destination / 'requirements.txt')
                copyfile(root / 'service-template/app.py', destination / 'app.py')
            ''',
            "service-template/requirements.txt": "fixture-export-kit==1.3\n",
            "service-template/app.py": "from fixture_export_kit import export_csv\n\n\ndef download(rows):\n    return export_csv(rows, headers=['name', 'email'])\n",
            "reference/requirements.txt": "fixture-export-kit==1.4\n",
            "reference/app.py": "from fixture_export_kit import export_csv\n\n\ndef download(rows):\n    return export_csv(rows, headers=['name', 'email'])\n",
            "docs/export-kit-releases.md": "Local mirror notes for the synthetic fixture package. 1.3 indexed the first row even with explicit headers. 1.4 supports header-only CSV with explicit headers.\n",
        },
    ),
    "04": (
        "PR 28 merged green even though it imports a UI primitive from a product module. "
        "The local boundary check still rejects that import. Where should we fix this?",
        {
            "README.md": "Run python scripts/check_ui.py to check the product/UI boundary.\n",
            "product/draft.py": "from ui.panel import open_panel\n",
            "scripts/check_ui.py": '''
                from pathlib import Path

                for path in Path("product").glob("*.py"):
                    if "from ui.panel import" in path.read_text():
                        raise SystemExit(f"{path}: use ui.dialog.confirm_delete")
            ''',
            ".github/workflows/check.yml": '''
                name: Checks
                on: pull_request
                jobs:
                  ui-boundaries:
                    if: github.event_name == 'push'
                    runs-on: ubuntu-latest
                    steps:
                      - uses: actions/checkout@v4
                      - run: python scripts/check_ui.py
            ''',
            "reports/pr-28.txt": "Revision 93fcae1. pull_request event. ui-boundaries skipped. PR check rollup green.\n",
        },
    ),
    "05": (
        "A support ticket says keyboard users lost focus after deleting a draft. "
        "Where should we fix this?",
        {
            "README.md": "Use the shared confirmDelete control. Reports should include deployment and the screen where deletion happened.\n",
            "ui/dialog.js": '''
                export function confirmDelete(remove, focusTarget) {
                    remove();
                    if (focusTarget?.isConnected) focusTarget.focus();
                }
            ''',
            "drafts/page.js": "import { confirmDelete } from '../ui/dialog.js';\nexport const deleteDraft = (remove, heading) => confirmDelete(remove, heading);\n",
            "reports/case-195.txt": "Pressed Enter to confirm. Draft disappeared and then my keyboard focus was gone. Build, screen, triggering control, and focus target were not captured.\n",
        },
    ),
    "06": (
        "Retried submissions should create one record. Clients retry the same request "
        "with the same key, but users still see two records. Where should we fix this?",
        {
            "README.md": "The public submit endpoint accepts a required retry key. A normal deployment has multiple workers.\n",
            "api/submit.py": '''
                def submit(key, payload, store):
                    previous = store.lookup(key)
                    if previous is not None:
                        return previous
                    return store.insert(key, payload)
            ''',
            "storage/schema.sql": '''
                CREATE TABLE submissions (
                    id INTEGER PRIMARY KEY,
                    retry_key TEXT NOT NULL,
                    payload TEXT NOT NULL
                );
            ''',
            "reports/retries.txt": "Worker A and B both logged lookup miss for key k82 at 07:02. Their insert calls returned ids 61 and 62. Sequential replay later returned 61.\n",
        },
    ),
    "07": (
        "Summarize the local setup instructions in two bullets for a teammate.",
        {
            "README.md": "Use Python 3.11. Run python -m unittest discover -s tests from the repository root.\n",
        },
    ),
    "08": (
        "The export ticket and the data-handling decision appear to disagree. "
        "Where should we fix the export so this can move forward?",
        {
            "README.md": "External exports use jobs/partner.py. Release intake follows docs/release.md.\n",
            "jobs/partner.py": '''
                def download(rows):
                    return [{'name': row['name'], 'email': row['email']} for row in rows]
            ''',
            "docs/decisions/DEC-017.md": (
                "Accepted. External partner exports omit personal email. "
                "Exceptions require Privacy approval recorded on this decision. Owner: Privacy.\n"
            ),
            "docs/release.md": (
                "If an acceptance criterion conflicts with an accepted decision, the ticket "
                "owner and the decision owner record the resolution before release.\n"
            ),
        },
    ),
}

TICKETS = {
    "01": "Accept an empty export with the same ordered columns as a populated export.",
    "02": "After confirming deletion from list or toolbar, remove the draft and return focus to the list.",
    "03": "An empty team export works in a newly generated service.",
    "04": "A PR with a prohibited product import cannot pass verification.",
    "05": "After keyboard confirmation, focus returns to the draft list.",
    "06": "Retries with the same key return the same record, including across workers.",
    "07": "Summarize the local setup instructions in two bullets.",
    "08": "External partner exports include name and personal email. Owner: Partner Integrations.",
}


def main():
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("destination", type=Path, help="a new output directory")
    parser.add_argument("--case", choices=CASES)
    args = parser.parse_args()
    args.destination.mkdir()
    cases = {args.case: CASES[args.case]} if args.case else CASES
    for case, (prompt, files) in cases.items():
        workspace = args.destination / case
        workspace.mkdir()
        ticket = f"FIX-{int(case) + 100}"
        request = prompt if case == "07" else TASK + prompt
        (workspace / "PROMPT.txt").write_text(
            f"Local copy of ticket {ticket} is in TICKET.md. Work from the supplied checkout.\n"
            "This exercise is local and read-only.\n\n" + request + "\n",
            encoding="utf-8",
        )
        (workspace / "TICKET.md").write_text(
            f"# {ticket}\n\n{prompt}\n\nAcceptance criterion: {TICKETS[case]}\n\n"
            "Scope: inspect this checkout and respond. Product changes and external actions are out of scope.\n",
            encoding="utf-8",
        )
        for name, contents in files.items():
            path = workspace / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(dedent(contents).lstrip("\n"), encoding="utf-8")


if __name__ == "__main__":
    main()
