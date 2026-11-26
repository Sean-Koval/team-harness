# Your first ticket with Claude Code

Use Claude Code for one small change in one company repository. Pick a Jira ticket with clear acceptance criteria and a test command. Start with a low-risk change that needs no extra release review.

## Install the work harness

Use your company-approved Claude Code login, GitHub CLI login and Atlassian connection. Keep the private team-harness copy and the work repository on company systems. Ask the team for the approved private copy with its [company overlay](../orgs/README.md) already built into `work-default@candidate`. Keep company projects, process skills, URLs, credentials and review details out of the public repository.

The install below assumes Python 3 with PyYAML and the private harness checkout at `~/src/team-harness`. Open a terminal in the **work repository**. On Windows, follow the [PowerShell commands](work-laptop-runbook.md#powershell).

```sh
harness_repo="$HOME/src/team-harness"
python3 "$harness_repo/scripts/install_local.py" "$harness_repo/harnesses/work-default" --scope project --channel candidate
python3 "$harness_repo/scripts/install_local.py" "$harness_repo/harnesses/work-default" --scope project --channel candidate --apply
python3 "$harness_repo/scripts/install_local.py" "$harness_repo/harnesses/work-default" --scope project --channel candidate --check
```

The first command previews the install, the second writes it and the third checks drift. The public `stable` channel is the CLI default and carries a placeholder org that files zero approval tickets. The standalone KAN-599 ZIP is a synthetic rehearsal. Use the company's approved candidate for real work.

From the work repository, set up the approved GitHub and Atlassian connections. Use the installer’s printed GitHub command if your team uses that binding. For Atlassian, use the approved session sign-in through Claude Code’s `/mcp`. The CI Jira credential follows a separate approval process. ai-dlc and Work Copilot are optional.

Run the doctor with the repository's own test command in place of `make test`. Repeat `--test-cmd` for each check and add `--github-host` for your company’s host if it uses GitHub Enterprise.

```sh
python3 "$harness_repo/scripts/doctor.py" "$harness_repo/harnesses/work-default" --scope project --skip capture --test-cmd "make test"
```

Review the doctor output before assigning a ticket. Use its exact suggested allow rules in `.claude/settings.local.json`. The current doctor reports unused ai-dlc as a fix and can flag placeholder strings in fallback text after the company overlay is installed.

Check the installed `.claude/skills/org-process/SKILL.md` and `.claude/skills/release-approvals/SKILL.md` against the approved candidate. Resolve problems with Claude Code, hooks, the channel, or required GitHub and Atlassian access before starting.

## Work the ticket

```sh
claude
```

Ask Claude Code to “Pick up KEY-123. Read our org process, make the change, run the ticket’s checks and prepare the PR for review.” Substitute your Jira key.

The agent reads the ticket, creates a branch keyed to it, makes and tests the change, and opens a draft PR. Keep the project-scope install files out of this ticket’s diff. Review `git status` and stage only the ticket’s paths. The [laptop runbook](work-laptop-runbook.md) lists the install paths to check.

For a team rule, inspect the owning code first. If the shared button already does the right thing but feature code bypasses it, make the existing PR lint check reject the direct import. Prove that the design-system wrapper can still import the primitive.

For the pilot, mark the Jira ticket `standards-change`. Check which build you installed. Public candidate r20 supplies `implement-standard` for manual use. To measure automatic intake, the private candidate must include the marked-issue hook. If that hook misses, open the installed skill before editing and record the manual recovery. [Where to put a team standard](working-with-standards.md)

## Review the PR

- Check that the title starts with the ticket key, the body has `Jira:` and `Docs:` lines, and the diff and test results match the ticket. Check rollout and rollback where relevant.
- After the PR opens, the agent follows `org-process` and the installed approval rules. It files or reuses each applicable agent-owned approval ticket, links it as required, and adds its gate line to the PR.
- If a gate is approved on the work ticket itself, look for the PR link there. The agent calls out any ticket or GitHub review a person needs to request.
- Check the gate summary against the company process. Confirm the required SRE review, and check database and architecture gates when the change triggers them. Keep any unverified requirement with its human owner and follow the company’s merge rules.
- Read the drafted review request and post it yourself. A person handles approval and merge. The agent never approves or merges.

See the [work laptop runbook](work-laptop-runbook.md) for prerequisites, install cleanup and optional local transcript capture.
