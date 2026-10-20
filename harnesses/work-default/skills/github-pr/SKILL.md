---
name: github-pr
description: Use when finishing work that becomes one or more pull requests, when writing what goes in a PR description, or when answering review comments. Covers the per-repository PR body in a change set, checks, and what never to do on GitHub.
---

# Pull requests

Everything is reviewed in GitHub. hangar pushes your branch and opens the PR as the factory's GitHub App, with the
branch name and title the repository's policy requires (the ticket key first: `SVC-412: add the retry queue`). In a
change set it opens one PR per changed repository and links them. You write what goes in each description.

## The description, per repository

End your turn with one section per changed repository, in this order:

- **Ticket:** the Jira key.
- **What and why:** two to five lines about this repository's change only.
- **Depends on:** what it needs from the sibling PRs ("needs database's migration 0042 merged first") or "none".
- **How it was tested:** the commands you ran in this checkout and their result.
- **Risk and rollout:** migrations, flags, resources created, anything a reviewer must do.
- **Not done:** anything in the ticket you left out, and why.

## Checks and reviews

- Each repository's CI runs on its PR. If a check fails, read its log, fix the cause and continue the job; re-run a
  check once only when its log shows an infrastructure failure, and say so.
- Answer every review comment, either with a commit that addresses it or with a short reason you disagree.
- Never merge, approve a PR, dismiss a review, enable auto-merge or change branch protection. hangar arms landing
  only after the repository's own approvers approve, and in the change set's order.
- Don't push to another repository's branch, and don't open PRs yourself with `gh` or the `github` MCP server's
  write tools: hangar opens them, so the links, trailers and landing order stay right.
