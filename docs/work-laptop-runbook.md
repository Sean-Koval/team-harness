# Work laptop runbook

How to run the `work-default` harness on a company laptop, end to end: ticket, branch, tested change, draft PR,
approval tickets, review request, and a measurement of each session afterwards. It was proven once in a scratch repo
with a fake tracker; no real company system was touched. How docs and tickets stay organized is in
[jira-confluence-organization.md](jira-confluence-organization.md).

Nothing company-specific belongs in this repository. Your company's org file and your team's process skill go in a
private fork (see [Before you start](#before-you-start)).

## The tools and what each does on the laptop

| Layer | Tool | What it does | In the first test? |
| --- | --- | --- | --- |
| Attention | Work Copilot | Shows what needs you, who is owed a reply and what you're waiting on | Optional |
| Doing | team-harness `work-default` | Claude Code reads the ticket, branches, changes, tests, opens a draft PR, files the approval tickets and drafts the review request. Never merges | Yes |
| Machine | ai-dlc | Installs and checks the toolchain; local guardrails; `ai-dlc next` | Yes, provisioning only |
| Bridge | hangar | `hangar trace import` turns a session transcript into a trace, offline. No server | Yes |
| Measure | flightdeck | Loads traces into local Parquet and answers "how did each ticket go" | Yes |
| Later | trace compiler, mesh | Evidence-backed labels; one-call ticket context | No |

A day, end to end:

1. **Morning:** Work Copilot (or Jira) shows the ticket to pick up.
2. **Start:** in the work repo, run `claude`, then: "Pick up KEY-123. Work it through our usual flow until it's
   ready for review."
3. **Agent:** reads the ticket and the org-process skill, keys the branch and commits, makes the change, runs the
   repo's tests, and opens a draft PR with `Jira:`, `Docs:` and one line per approval gate. It files the approval
   tickets, links them, and drafts the review request.
4. **You:** read the PR, mark it ready and post the drafted request in the team's review room.
5. **Approvers** approve on their tickets. The PR check confirms each gate line names an approved ticket.
6. **You merge.** The harness never merges at work.
7. **End of day:** capture the day's sessions with flightdeck and read one row per session.

## Before you start

**What has to land first.** Until these merge, check out their branches instead.

- hangar PR 454 (`hangar trace import`).
- flightdeck PR 100 (`flightdeck ingest file`), and PR 107 if work uses GitHub Enterprise.
- team-harness PR 7 (parameterised work-system layer) and PR 10 (approval specs).
- team-harness PRs 8, 9 and 11 (org overlay, gate check, local installer) after their safety fixes: KAN-366, KAN-365
  and KAN-367. KAN-371 (merge-rule bypasses) rebases on top.
- An ai-dlc release (KAN-261), so the laptop installs a reviewed version instead of main.

**Your company's content, in a private fork only.** Copy this repository privately. Add
`orgs/<company>/org.yaml` (projects, gates, review room) and your team's process skill in
`orgs/<company>/skills/org-process/`. Never put either in the public repository.

Your ESS work ops skill is that process skill. It lives on your work computer, so make the private fork there and
copy the skill into `orgs/<company>/skills/org-process/` (its `SKILL.md` and anything it references). Step 2 then
installs it into the work repo with the rest of `work-default`. Name the label that triggers the ESS gate (KAN-355)
in `org.yaml`. The Jira and Confluence structure the flow needs is in [jira-confluence-setup.md](jira-confluence-setup.md).

## Setup, in order

**Step 0. Preflight.**

- The work laptop is a Mac, so everything below runs natively (KAN-370). Install the Xcode Command Line Tools
  first; the plugin hooks call `python3`.
- Coworkers on Windows install and run the team-harness hooks natively, in PowerShell or cmd, with the Python
  launcher (`py -3`); CI runs those tests on Windows (KAN-460). WSL2 is a fallback only, for when the launcher isn't
  allowed. ai-dlc itself has no native Windows install yet (ai-dlc #172), so Step 1 still needs WSL2 there. Work
  Copilot's Windows keyring fix (three OAuth storage tests fail on Windows CI) stays in scope for them.
- Behind a company proxy, set `HTTPS_PROXY`, and `SSL_CERT_FILE` if the proxy inspects TLS.
- Run `gh auth login` against the company GitHub host.
- Pick the model route first. Use a company-approved login, not a personal plan.

**Step 1. ai-dlc (the machine).**

```sh
git clone https://github.com/Sean-Koval/ai-dlc.git && cd ai-dlc
sh scripts/bootstrap.sh --plan      # prints what it would install
sh scripts/bootstrap.sh --source    # if mise downloads fail behind the proxy: uv sync --locked
ai-dlc doctor
```

Add the two directories bootstrap prints to `PATH`. `doctor` prints JSON today (KAN-364): look for `missing` and
`next`. `project check` and `setup` need mise (KAN-354). Don't adopt ai-dlc into a company repo for the first test.
Adoption adds about 26 files that need review, and `work finish` can't pass its CI gate there yet (KAN-368).

**Step 2. team-harness `work-default` (the flow).**

```sh
git clone <your private fork> && cd team-harness
python3 scripts/install_local.py harnesses/work-default --scope project --target ~/src/<work-repo>          # dry run
python3 scripts/install_local.py harnesses/work-default --scope project --target ~/src/<work-repo> --apply
python3 scripts/install_local.py harnesses/work-default --scope project --target ~/src/<work-repo> --check
```

On Windows, run the same lines with `py -3` in place of `python3`, and `$HOME\src\<work-repo>` as the target. The
installed hooks run with `py -3` as well, and `--uninstall` leaves `settings.json` byte for byte as it was, unless you changed it since.

Use project scope, one repo at a time, until KAN-367 lands; user scope puts the guards on every session. Run the two
`claude mcp add` lines the install prints (GitHub and Jira). The GitHub credential comes from your secret manager. Jira
needs no static credential at work today (KAN-369): log in to the Atlassian MCP from the session, and that login does
the Jira work. It does not stand in for a lifecycle credential, and a lifecycle credential does not stand in for it.
Then add the repo's own test and check commands to the allowlist in `.claude/settings.json`. The test run lost a whole
pass without it.

**Step 3. Capture tools (hangar import and flightdeck).**

```sh
git clone https://github.com/Sean-Koval/hangar.git && (cd hangar && git fetch origin pull/454/head:pr-454 && git checkout pr-454 && uv sync)
git clone https://github.com/Sean-Koval/flightdeck.git && (cd flightdeck && git fetch origin pull/100/head:pr-100 && git checkout pr-100 && uv sync)
mkdir -p ~/.flightdeck/data && chmod 700 ~/.flightdeck/data
```

Keep `~/.flightdeck` out of git checkouts and synced folders. It holds a second copy of your transcripts.

**Step 4 (optional). Work Copilot.**

```sh
git clone https://github.com/Sean-Koval/work-copilot.git && cd work-copilot
work-copilot init && work-copilot doctor
```

Point its vault at a company-approved folder, never a personal vault. It has no live Jira or Confluence source yet.

## The first test ticket

Pick one that is in one repo, small and low risk, with acceptance criteria and a verify command, and that needs no
extra release review. In that repo run `claude` and send: "Pick up KEY-123. Work it through our usual flow until it's
ready for review."

What good looks like:

- a "Started. Plan:" comment on the ticket;
- a branch and commits that start with the key;
- tests run and passing before any push;
- a draft PR with `Jira:`, `Docs:` and one line per gate;
- approval tickets filed after the PR and linked to it;
- a review request drafted, not posted;
- anything out of scope filed as its own proposed ticket;
- no transition, no merge, nothing posted to chat.

If it stops early, read its last message. It names what it couldn't run.

## Reading the results

The agent's final message names the PR, the gate tickets and the drafted request. The PR check's summary table shows
each gate: its line, its ticket, whether it applies, and its state. At the end of the day:

```sh
for t in ~/.claude/projects/*/*.jsonl; do
  d=~/.flightdeck/import/$(basename "$t" .jsonl)
  (cd ~/src/hangar && uv run hangar trace import "$t" --out "$d") && (cd ~/src/flightdeck && uv run flightdeck ingest file "$d/trace.json")
done
cd ~/src/flightdeck && uv run flightdeck query --data ~/.flightdeck/data -- "$(grep -v '^--' ~/src/team-harness/docs/flightdeck-sdlc-runs.sql)"
```

[`flightdeck-sdlc-runs.sql`](flightdeck-sdlc-runs.sql) prints one row per session. It will ship as `flightdeck report sessions` (KAN-358).

| Column | What to look at |
| --- | --- |
| `usd`, `mins` | Cost and time per ticket. The scratch ticket cost $1.52 |
| `ticket` | Which ticket the session worked |
| `tool_errors` | Check first. Many errors usually mean a missing allowlist entry or a broken command |
| `prs_opened` | More than one for one ticket means churn |
| `ci_waits` | High means the agent sat polling CI |
| `test_runs`, `edits` | Tests should come before the push |
| `jira_calls` | Calls to Jira; zero means it never read the ticket |

Not useful yet: `metrics weekly` reads blanks on laptop sessions, and the behavior specs return `not_applicable`
until KAN-353.

## What leaves the laptop

**Stays local:** `hangar trace import`, `flightdeck ingest file`, `query` and `spec test`, the trace compiler, Work
Copilot's store and vault, and the harness hooks.

**Leaves, so it needs sign-off:**

- Model traffic: code, ticket text and transcripts go to the model provider.
- The Jira and GitHub MCP connections the install prints. An Atlassian admin may need to allow the remote MCP.
- No PR-check Jira token until the credential method is signed off in KAN-450 (KAN-369 chose none for now). Until
  then the ticket check is off at work, and the approval gates report `unverified` and fail closed (KAN-365), so a
  person must approve the merge. Once approved, it is a personal Jira API token with scopes (read scopes only),
  stored as a CI secret.
- Off by default until KAN-214: a cloud flightdeck data plane, `report post`, `ingest github`, and any hangar server.

Never send work content to a personal tracker or knowledge base.

## Doctor and onboarding

These exist today: `bootstrap.sh --plan`, `ai-dlc doctor`, `ai-dlc next`, `install_local.py --check`,
`work-copilot doctor`, and `hangar doctor` (server only). None checks the whole laptop. The plan is one laptop doctor,
in ai-dlc, that calls each tool's own check and prints one table of ok, warning and fix command.

| Check | Ticket |
| --- | --- |
| Fresh-laptop preflight; readable output | KAN-363, KAN-364 |
| Harness: Claude Code version, hooks run, MCP servers answer, overlay applied, allowlist covers the repo's checks | KAN-372 |
| hangar local: Python, uv, container runtime, proxy CA, model login | KAN-351 |
| flightdeck: DuckDB offline, data dir private and not synced | KAN-360 |
| One-command daily capture | KAN-345, KAN-361 |
| trace compiler and mesh doctors | KAN-346, KAN-348 |

## Decisions it rests on

Each was a Decision ticket in KAN, now decided. The picks:

| Ticket | Question | Chosen |
| --- | --- | --- |
| KAN-375 | Where the org overlay and process skill live | The laptop-only overlay first; then the company repo pins this one as upstream once teammates join |
| KAN-355 | When a change needs the ESS review step | A gate a person files, triggered by a ticket label named in the private overlay |
| KAN-370 | Laptop OS | Native on macOS (the work laptop is a Mac); native on Windows for the harness (KAN-460), WSL2 only as a fallback |
| KAN-369 | Which Jira credential work allows | None for now; the Atlassian MCP in the session does the Jira work |
| KAN-368 | CI evidence for `ai-dlc work finish` | Finish on spec-current and PR-merged for the trial; company branch protection enforces CI |
| KAN-362 | Which flightdeck paths run before sign-off | Local only; GitHub ingest once a read-only work token is allowed |
| KAN-356 | How far hangar goes in the first test | Trace import only; local hangar once KAN-214 gives a company key |
| KAN-350, KAN-343 | Trace compiler and mesh in the first test | Leave both out for now |
