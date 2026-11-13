---
name: github-pr
description: Use when opening or updating a pull request, linking it to its issue or ticket, or moving a GitHub Projects item. Covers branch naming, the PR body, checks and the Projects status field.
---

# Pull requests and GitHub Projects

The team reviews everything in GitHub. One ticket, one branch, one pull request. Use the `github` MCP server's tools
(or `gh` when the environment provides it); both act with the environment's token, never yours.

## Branch and commits

- Branch from the default branch: `<ticket-key-or-issue-number>-<short-slug>` (`ABC-123-export-csv`, `412-fix-null-total`).
- Conventional commit prefixes. Reference the ticket in the first commit's body.
- Don't force-push a branch someone else has reviewed; add commits instead.

## Opening the PR

1. Push the branch, then open the PR as a **draft** until the repository's checks pass locally.
2. Title: `<type>: <what changes>` (under 72 characters). Body, in this order:
   - **Ticket:** the Jira key or `Fixes #<n>` for a GitHub issue.
   - **What and why:** two to five lines.
   - **How it was tested:** the commands you ran and their result; for a production investigation, the log query and
     cluster objects you looked at.
   - **Risk and rollout:** migrations, flags, anything a reviewer must do.
   - **Not done:** anything in the ticket you left out, and why.
3. Mark it ready for review when CI is green. If a check fails, read its log, fix the cause and push. Re-run a check
   once only when its log shows an infrastructure failure, and say so in the PR.
4. Never merge, approve your own PR, dismiss a review or change branch protection.

## GitHub Projects

The team's board has a single-select **Status** field (`Todo`, `In progress`, `In review`, `Done`).

- When you start: add the issue to the project if it isn't there and set Status to `In progress`.
- When the PR is ready for review: set the issue's item to `In review` and add the PR to the project.
- Leave `Done` to the merge automation or a person.
- If the project has an **Agent** or **Owner** field, set it to the agent identity the environment gives you; don't
  reassign people.

## Review comments

Answer every review comment, either with a commit that addresses it (reply with the commit) or with a short reason
you disagree. Re-request review when all threads are answered.
