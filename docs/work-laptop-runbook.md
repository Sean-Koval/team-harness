# Work laptop runbook

Start with [Your first ticket with Claude Code](first-loop.md). This runbook covers setup, project-scope files and optional local capture. A prior scratch run used a fake tracker and cost $1.52 for one ticket. That run is evidence for the local capture path. It used synthetic data and no company systems.

| Tool | What it does |
| --- | --- |
| Claude Code with `work-default` | Works the Jira ticket through a tested change, a PR and a draft review request |
| ai-dlc | Optional toolchain and workflow support |
| Work Copilot | Optional view of work, obligations and priorities |
| hangar and flightdeck | Optional local transcript import and session measurement |

For document and ticket organization, see the [Jira and Confluence organization guide](jira-confluence-organization.md).

## Before you start

- Install Git, Python 3 with PyYAML, Claude Code and the GitHub CLI through approved sources. Use your company's model route and sign in to its GitHub host with `gh auth login`. On macOS, use the Xcode Command Line Tools if needed for Git. On Windows, the installer and hooks run natively using `py -3`. Set `HTTPS_PROXY` and `SSL_CERT_FILE` if your company's proxy and certificates require them.
- Get the approved private copy of team-harness. Keep its Git history. The maintainer sets `shared/work-system/targets.yaml` to the company overlay under `orgs/<company>/`. The overlay keeps the company’s `org.yaml`, its `org-process` skill and any related ESS instructions in the approved private copy. Follow the [overlay build instructions](../orgs/README.md) and wait for main to build the candidate before teammates install it.
- Confirm the company's GitHub and Atlassian connections and the work repository’s test commands. See the [Jira and Confluence setup](jira-confluence-setup.md).
- Keep the public repository free of company content. The public `stable` channel installs the placeholder org, which files zero approval tickets. The KAN-599 ZIP is a standalone synthetic rehearsal. Use the company's approved private candidate for real tickets.

## Setup

### 1. Prepare Claude Code

Use the Claude Code version named by the installer plan or a compatible newer version. Configure the required GitHub and Atlassian access in the work repository. Use the work session’s Atlassian MCP sign-in through `/mcp`. Ask the organization before configuring a separate Jira credential for PR checks. If CI cannot verify a required approval, the gate fails closed. Resolve it through the company’s review process before merging.

ai-dlc and Work Copilot are optional. Use Jira directly to pick up the first ticket. If the team uses ai-dlc later, use its approved release. Follow its [installation instructions](https://github.com/Sean-Koval/ai-dlc) and check the machine with `ai-dlc doctor`.

If you use Work Copilot, install it through an approved source and follow its setup and doctor instructions. [Work Copilot repository](https://github.com/Sean-Koval/work-copilot) Use a company-approved data directory and vault. The project install prints a machine-local MCP command and can generate a Work Copilot overlay file from the private org configuration.

Set `WORK_COPILOT_DATA_DIR` before you run the printed MCP command. Claude Code stores the value the command supplies. To change it later, use `claude mcp remove --scope local work-copilot` and run the printed command with the new value.

### 2. Install in the work repository

Run the project-scope candidate install, check and doctor from the [first-loop guide](first-loop.md). Project scope keeps these guards in the work repository. On Windows, use `py -3` and PowerShell. The installer runs the guards during `--apply` and `--check`, and a guard that fails to start is a setup problem.

Review the doctor's individual results. It accepts repeatable `--test-cmd` flags or reads `[checks.commands]` from `ai-dlc.toml` when present. Add the necessary rules it suggests to `.claude/settings.local.json`. Doctor `--live` makes a model call and can probe configured HTTP tools. Use it only on the approved model and service connections.

Project-scope installs can change `CLAUDE.md`, `.gitignore` and files under `.claude/`, including skills, agents, hooks, the guide, shared settings and manifests. When you register a project-scoped MCP server, Claude Code can also write `.mcp.json`. Review `git status` before committing. Stage only the ticket’s paths. Commit harness configuration only through a separate, deliberate team change, with credentials kept out of Git. The installer ignores `.claude/*.local.json` in Git when those files would otherwise be visible.

To remove the harness, use the same installer and project scope with `--uninstall`. It uses the manifests to remove its own additions and reports edited files it leaves for you to review.

#### PowerShell

Open PowerShell in the work repository. Change the harness path if needed. Substitute the repository’s test command for `make test` and run the doctor after configuring GitHub and Atlassian.

```powershell
$harnessRepo = Join-Path $HOME 'src/team-harness'
$workHarness = Join-Path $harnessRepo 'harnesses/work-default'
$installer = Join-Path $harnessRepo 'scripts/install_local.py'
py -3 $installer $workHarness --scope project --channel candidate
py -3 $installer $workHarness --scope project --channel candidate --apply
py -3 $installer $workHarness --scope project --channel candidate --check
py -3 (Join-Path $harnessRepo 'scripts/doctor.py') $workHarness --scope project --skip capture --test-cmd "make test"
```

### 3. Set up local capture if the team uses it

Install hangar and flightdeck from your company's approved source. Use a release or revision that supports these commands. Neither tool is required for the first ticket.

```sh
hangar trace import --help
flightdeck ingest file --help
mkdir -p "$HOME/.flightdeck/data"
chmod 700 "$HOME/.flightdeck" "$HOME/.flightdeck/data"
```

Run these commands from a POSIX shell. Keep transcripts and capture output outside Git checkouts and synced folders, in company-approved storage. The doctor checks for both commands on `PATH` and a local Claude Code transcript directory. Use `--skip capture` if you are doing the first loop without capture.

## Review and measure a session

In the work repo, follow the [first-loop guide](first-loop.md) from the Jira ticket through human review. Check the changed paths, test results and PR check summary. The agent's hand-back names the PR, applicable gates and any next step for a person. A person posts the drafted review request, and the team’s approvers and merger handle their parts.

For a capture run, set `transcript` to one approved local Claude Code JSONL file. Then import and query it from a POSIX shell. These commands assume the private harness checkout is at `~/src/team-harness`.

```sh
transcript="$HOME/.claude/projects/PROJECT/SESSION.jsonl"
capture="$HOME/.flightdeck/import/$(basename "$transcript" .jsonl)"
hangar trace import "$transcript" --out "$capture" &&
  flightdeck ingest file "$capture/trace.json" &&
  flightdeck query --data "$HOME/.flightdeck/data" -- "$(sed '/^--/d' "$HOME/src/team-harness/docs/flightdeck-sdlc-runs.sql")"
```

The [session query](flightdeck-sdlc-runs.sql) prints one row per session.

| Column | What to look at |
| --- | --- |
| `usd`, `mins` | Cost and time for the session |
| `ticket` | Which ticket the session worked |
| `tool_errors` | Start here. Errors can point to a missing allowlist entry or broken command |
| `prs_opened` | Multiple PRs for one ticket can point to rework |
| `ci_waits` | High counts can point to repeated CI polling |
| `test_runs`, `edits` | Compare verification with the changes the session made |
| `jira_calls` | Calls to Jira |

## Data handling

**Stays local:** `hangar trace import`, `flightdeck ingest file`, local queries and spec tests, the trace compiler, Work Copilot's store and vault, and the harness hooks.

**Requires company sign-off:**

- Model traffic can include code, ticket text and transcripts sent to the model provider.
- GitHub and Atlassian MCP calls go to the configured services. An Atlassian admin may need to allow the remote MCP.
- The session's Atlassian login handles Jira work. PR-check credentials require separate approval (KAN-450). With no approved CI credential, a gate that requires Jira evidence reports `unverified` and fails closed. Follow the company process to resolve it before merge.
- Keep the cloud flightdeck data plane, `report post`, `ingest github` and hangar servers off until approved (KAN-214).

Keep work content in company-approved storage, trackers and knowledge bases.

## Doctor and onboarding

Use `install_local.py --check` and `scripts/doctor.py` for the harness. Each optional tool has its own checks. They include `bootstrap.sh --plan`, `ai-dlc doctor`, `ai-dlc next`, `work-copilot doctor`, and `hangar doctor` for a hangar server.

| Check | Ticket |
| --- | --- |
| Fresh-laptop preflight and readable output | KAN-363, KAN-364 |
| Claude Code, hooks, MCP servers, org overlay and repository allowlist | KAN-372 |
| Local hangar Python, uv, container runtime, proxy CA and model login | KAN-351 |
| flightdeck DuckDB offline and private data directory | KAN-360 |
| One-command daily capture | KAN-345, KAN-361 |
| Trace compiler and mesh doctors | KAN-346, KAN-348 |

## Decisions it rests on

These are the decisions behind the laptop trial. Check KAN-605 for the current decision on where teammates get the private copy.

| Ticket | Question | Chosen |
| --- | --- | --- |
| KAN-375 | Where the org overlay and process skill live | Laptop-only overlay first, then a company repo that pins this one as upstream |
| KAN-355 | When a change needs the ESS review step | A gate a person files, triggered by a ticket label named in the private overlay |
| KAN-370, KAN-460 | Laptop OS | Native on macOS and Windows for the harness, with WSL2 as a fallback |
| KAN-369 | Which Jira credential work allows | Use the session's Atlassian MCP login. A static credential is pending approval |
| KAN-368 | CI evidence for `ai-dlc work finish` | Finish on spec-current and PR-merged for the trial. Company branch protection enforces CI |
| KAN-362 | Which flightdeck paths run before sign-off | Local capture only. GitHub ingest needs an approved read-only work token |
| KAN-356 | How far hangar goes in the first test | Trace import only. Local hangar needs the company key in KAN-214 |
| KAN-350, KAN-343 | Trace compiler and mesh in the first test | Defer both |
