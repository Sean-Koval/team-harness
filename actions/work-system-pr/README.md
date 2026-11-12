# Work-system PR check

The gate every surface crosses. Whether a change came from a hangar job, a local Claude Code or Codex session, a cloud
session or a person in the browser, it reaches `main` through a pull request, so the work-system rules are checked
here (the harness hook in `shared/work-system/` only catches them earlier). See [`check.py`](check.py) for the rules.

## Adopt it in a repository

1. Add `.github/workflows/work-system.yml`, pinning this repository by commit (constraint: no moving refs):

   ```yaml
   name: work-system
   on:
     pull_request:
       types: [opened, edited, synchronize, reopened, labeled, unlabeled]
   permissions:
     contents: read
     pull-requests: read
   jobs:
     pr:
       runs-on: ubuntu-24.04
       steps:
         - uses: Sean-Koval/team-harness/actions/work-system-pr@<commit sha>
           with:
             jira-base-url: https://seanmkoval.atlassian.net
             jira-user: ${{ secrets.JIRA_READ_USER }}
             jira-token: ${{ secrets.JIRA_READ_TOKEN }}
   ```

   `edited` matters: fixing the title or body re-runs the check without a new commit.
2. Copy [`templates/pull_request_template.md`](../../templates/pull_request_template.md) to `.github/`.
3. Make `work-system / pr` a required status check on `main` (branch protection or a ruleset).
4. Optional, for the ticket check: a Jira API token from an account that can only browse the project, stored as the two
   secrets. Without them the check still runs rules 1-5 and says the ticket was not checked.

At work, set `jira-base-url` to the company site and `key-pattern` if keys look different.

## Hold merge on the org's approval gates

A company's org overlay (`orgs/<org>/org.yaml`, schema `team-harness.org/v1`) lists merge gates: approval tickets that
must exist, and be approved, before a PR merges. Pass the file as `org-file` and the check enforces them.

```yaml
name: work-system
on:
  pull_request:
    # edited: a gate line added to the body re-runs the check; labeled/unlabeled: label gates
    types: [opened, edited, synchronize, reopened, labeled, unlabeled]
permissions:
  contents: read        # the org file at the base commit
  pull-requests: read   # the PR's files
jobs:
  pr:
    runs-on: ubuntu-24.04
    steps:
      - uses: Sean-Koval/team-harness/actions/work-system-pr@<commit sha>
        with:
          org-file: orgs/example-co/org.yaml
          jira-base-url: https://COMPANY-SITE.atlassian.net
          jira-user: ${{ secrets.JIRA_READ_USER }}
          jira-token: ${{ secrets.JIRA_READ_TOKEN }}
```

**Re-run the check after the approval.** Approving the gate ticket in Jira sends GitHub no event, so the failed
`work-system / pr` run stays failed. Once the SRE (or other) ticket is approved, re-run the job from the PR's Checks
tab (or `gh run rerun <run id> --failed`); editing the PR body also re-runs it.

**The gates come from the base commit.** The check reads `org-file` at the PR's base commit through the contents API,
not from the checkout, so a PR can't loosen its own gates (for example by setting `placeholder: true`). A PR that
changes the org file is held to the base commit's version; its change applies from the next PR. If the file can't be
read at the base commit (it is new, or the API failed), the checked-out copy is used only when the PR doesn't change
it; otherwise the check fails and a maintainer merges the org-file change.

**What each gate needs.** For every gate whose `when` matches the PR (`always`; `paths` globs over the changed files,
where `**/` also matches the repository root, so `**/Dockerfile` matches `Dockerfile`; or `labels`, compared
case-insensitively against the PR's labels and the work ticket's Jira labels), the body needs a `<pr_line>: <KEY>`
line, such as `SRE: SREPROJ-789`, in the gate ticket type's project. A missing line, or one that says `pending`, fails
and names the gate, its ticket type and its project. A gate with `filed_by: person` fails the same way; its message
says a person files that ticket. The gates hold on exempt PRs too: an exemption skips the ticket rules, not the
approvals.

With Jira credentials, each gate ticket must:

- exist and be in the gate ticket type's project, with its `issue_type` (an Epic or an old Story doesn't count);
- for `links: [work]`, have an issue link to the PR's work ticket (the title's key);
- for `links: [pr]`, have the PR's URL as a remote link or in its description;
- if the gate lists `approved_statuses`, be in one of them, so merge waits on the approval itself.

**It fails closed.** A gate with `approved_statuses` fails (state `unverified`) when its ticket can't be read: no Jira
credentials (fork and Dependabot PRs get no secrets), Jira errors or times out, or answers with something other than
JSON, such as an SSO login page. Set `allow-unverified: "true"` only for a repository that knowingly accepts approvals
it can't verify; such gates then pass with a warning. When the work ticket's labels can't be read, gates with
`when: labels` apply, as gates with `when: paths` do when the PR's files can't be listed. Gates without
`approved_statuses` only warn when Jira can't be read.

An org file marked `placeholder: true`, like the shipped example, is not enforced: the check warns instead. An org file
that can't be read or doesn't fit the schema fails the check with the reason. The job summary lists each gate and its
state. The action reads YAML with PyYAML; if the runner's `python3` lacks it, the action installs `pyyaml==6.0.3` into
a temporary venv.
