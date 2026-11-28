# Connect the three tools in a work repository

Ask the team maintainer for the approved private, full-history harness copy with the company overlay built into `work-default@candidate`. The public example's placeholder overlay files no approval tickets. [Private distribution decision](https://seanmkoval.atlassian.net/browse/KAN-605)

## Prepare the tools

Install AI-DLC from the team's reviewed source ref using `sh scripts/bootstrap.sh --source`. Use the executable path the bootstrap prints. From outside the repo, run `ai-dlc doctor` and `ai-dlc project onboard --help`. The v0.4.0 release predates the planner. From the work repo, use the existing project's `ai-dlc project onboard --root .`. For an unconfigured repo, add `--preset generic --agent-client claude-code` to preview what adopting it would change. Review adoption and rendering separately before the trial ticket. [AI-DLC work-computer setup](https://github.com/Sean-Koval/ai-dlc/blob/a51244c9468e1f75b87582f3a59805c9b0e2ab26/docs/workflows/work-computer-setup.md)

Install the approved Work Copilot revision as a command available on Claude Code's PATH. Run `work-copilot smoke` and look for `"success": true`. Choose an approved, work-only Markdown vault and a separate private data directory owned by your local account. Keep both outside the product checkout and out of personal sync. Work Copilot scans Markdown recursively inside the selected vault. It stores work data locally, while Claude's model uses your approved model route. [Work Copilot setup](https://github.com/Sean-Koval/work-copilot/blob/3ca58410d89118ce6b41d194bede848ac6032afb/docs/GETTING_STARTED.md)

## Install in the work repository

From the work repo, substitute your actual approved paths. Ensure the same Python 3.10+ interpreter can import PyYAML. Preview, install and check the candidate.

```sh
export KNOWLEDGE_REPO=/absolute/path/to/approved/knowledge-repo
export WORK_COPILOT_DATA_DIR=/absolute/path/to/private/work-copilot-data
vault=/absolute/path/to/approved/work-only-vault
harness=/absolute/path/to/approved/private/team-harness
python3 -c 'import sys, yaml; assert sys.version_info >= (3, 10)'
python3 "$harness/scripts/install_local.py" "$harness/harnesses/work-default" --scope project --channel candidate
python3 "$harness/scripts/install_local.py" "$harness/harnesses/work-default" --scope project --channel candidate --apply
python3 "$harness/scripts/install_local.py" "$harness/harnesses/work-default" --scope project --channel candidate --check
```

Expect `clean: work-default@candidate` from the check. Use the printed company overlay render and apply commands. Verify the result and launch the dashboard with the same data directory:

```sh
work-copilot --data-dir "$WORK_COPILOT_DATA_DIR" overlay show
work-copilot --data-dir "$WORK_COPILOT_DATA_DIR" serve --vault "$vault"
```

## Verify each connection

Open <http://127.0.0.1:8765>. In a second terminal with the same settings, run the installer's printed local tool registrations for missing entries from the work repo. Connect GitHub and Atlassian using the methods your company approved. In Claude Code, approve the project-scoped AI-DLC server when prompted. Work Copilot's printed command uses Claude Code's `local` scope and saves the concrete value of `WORK_COPILOT_DATA_DIR` for this machine and repo. Use that registration alone if the Work Copilot wizard also offers a user-scoped one. Run `work-copilot --data-dir "$WORK_COPILOT_DATA_DIR" doctor --vault "$vault"` from the work repo to check its local registration. The clone launchers change into their own directory, so use the installed command for this check.

Verify the intended GitHub account with `gh auth status --hostname APPROVED_HOST`. In Claude Code's `/mcp`, confirm AI-DLC, Work Copilot and the required GitHub and Atlassian connections. GitHub CLI sign-in, any approved GitHub MCP binding, Atlassian session OAuth and the separate CI Jira credential serve different clients. Use the approved Atlassian login for the work session and follow company process for any unverified CI approval.

Replace `make test` with the work repo's real check command. Add only the exact local allow rules needed from the doctor's output. If it reports a placeholder, compare the installed `org-process` and `release-approvals` skills to the approved candidate before proceeding. The current check can find placeholder text in fallback instructions.

```sh
python3 "$harness/scripts/doctor.py" "$harness/harnesses/work-default" --scope project --skip capture --test-cmd "make test"
```

Capture a permitted, uniquely named note through the dashboard. Ask Claude to find it through Work Copilot and cite one passage with its source. Compare the passage to the original and confirm that the dashboard and MCP used the same workspace. Ask AI-DLC for a known record from the intended repo, then run `ai-dlc work validate --all` from the work repo if it has configured work records. Check that the named record and spec reference belong to this repo.

## Retire the trial

Before staging, inspect `git status` and stage only ticket paths. Keep harness install files and MCP configuration in their own reviewed change. To retire the trial, stop the dashboard with Ctrl+C. From the work repo, remove only Claude MCP entries added for this trial, with the scope used to add them. For example:

```sh
claude mcp remove --scope local work-copilot
claude mcp remove --scope project ai-dlc
python3 "$harness/scripts/install_local.py" "$harness/harnesses/work-default" --scope project --uninstall
git status --short
```

Review any edited install files the uninstaller leaves. Keep or remove the separate Work Copilot trial data through the team's storage process.
