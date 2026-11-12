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
4. Optional, for the ticket check: an organisation-approved personal Jira API token with scopes (read scopes only),
   from an account that can only browse the project, stored with its account email as the two secrets. Without them the
   check still runs rules 1-5 and says the ticket was not checked.

At work, set `jira-base-url` to the company site and `key-pattern` if keys look different. No static Jira credential
is used at work today (KAN-369): leave `jira-user` and `jira-token` unset until the credential method is signed off
in KAN-450. Until then the check runs rules 1-5 without the ticket check, and the org's approval gates report
`unverified` and fail closed (KAN-365), so a person must approve the merge. There is no setting that lets an
unverified gate pass.
