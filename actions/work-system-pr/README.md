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
must exist before a PR merges. Pass the file as `org-file` and the check enforces them. The check needs the file
on disk, so check out the base branch first; the PR then can't loosen its own gates.

```yaml
jobs:
  pr:
    runs-on: ubuntu-24.04
    steps:
      - uses: actions/checkout@v5
        with:
          ref: ${{ github.event.pull_request.base.sha }}   # the gates as merged, not as the PR edits them
      - uses: Sean-Koval/team-harness/actions/work-system-pr@<commit sha>
        with:
          org-file: orgs/example-co/org.yaml
          jira-base-url: https://COMPANY-SITE.atlassian.net
          jira-user: ${{ secrets.JIRA_READ_USER }}
          jira-token: ${{ secrets.JIRA_READ_TOKEN }}
```

For every gate whose `when` matches the PR (`always`, `paths` globs over the changed files, or `labels`), the body
needs a `<pr_line>: <KEY>` line, such as `SRE: SREPROJ-789`. A missing line, or one that says `pending`, fails and names
the gate, its ticket type and its project. A gate with `filed_by: person` fails the same way; its message says a person
files that ticket. The gates hold on exempt PRs too: an exemption skips the ticket rules, not the approvals.

With Jira credentials, each gate key must exist and be in the gate ticket type's project. A gate that lists
`approved_statuses` also needs its ticket in one of them, so merge waits on the approval itself. Without credentials,
only the key's project prefix is checked.

An org file marked `placeholder: true`, like the shipped example, is not enforced: the check warns instead. An org file
that can't be read or doesn't fit the schema fails the check with the reason. The job summary lists each gate and its
state. The action reads YAML with PyYAML; if the runner's `python3` lacks it, the action installs `pyyaml==6.0.3` into
a temporary venv.
