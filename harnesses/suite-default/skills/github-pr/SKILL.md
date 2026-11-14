---
name: github-pr
description: Use when finishing work that becomes one or more pull requests, when writing a PR description, when answering review comments, or before merging. Covers who opens the PR on each surface, the title and body contract the PR check enforces, change-set descriptions, the merge rule, and what never to do on GitHub.
---

# Pull requests

One ticket, one branch, one PR for each changed repository. Everything is reviewed in GitHub. The work-system PR check
fails any PR that breaks the contract below, whichever surface opened it.

## Who opens it

- **In a hangar job:** hangar pushes and opens the PR as its GitHub App, with the key in the branch and the title. In
  a change set, it opens one PR per changed repository and links them. You end your turn with the description below.
  Don't open PRs yourself with `gh` or the `github` MCP server's write tools, so that the links, trailers and landing
  order stay right.
- **In a local or cloud session:** push the branch and open the PR yourself:

  `gh pr create --draft --title '<KEY>: <what changes>' --body-file <file>`

  Mark it ready for review once the repository's checks pass, unless it carries the label `needs-owner-review` or
  its body has an `Owner review:` line (read both: `gh pr view <n> --json labels,body`). That PR stays a draft until
  Sean has reviewed it and marks it ready: never mark it ready, remove the label, drop its `Owner review:` line
  or open a new PR for its branch yourself. In a cloud session whose branch name was assigned,
  keep that branch: the title and the `Jira:` line link the PR.

## The contract

- **Title:** `<KEY>: <what changes>`, under 72 characters.
- **Body:** use the repository's PR template when it has one. Otherwise, in this order:
  - `Jira: <KEY>` on its own line, with the same key as the title.
  - `Docs: <files or Confluence page you updated, or "none needed - why">` (`work-docs`).
  - `Decision: <KEY>`, only when the PR implements a Decision that binds code; the PR then adds the ADR.
  - **What and why:** two to five lines, about this repository's change only.
  - **Depends on:** in a change set, what this PR needs from the sibling PRs ("needs database's migration 0042 merged
    first"), or "none".
  - **How it was verified:** the commands you ran in this checkout and their result.
  - **Risk and rollout:** migrations, flags, resources created, anything a reviewer must do.
  - **Not done:** anything in the ticket you left out, and why.

## Approvals

None beyond the PR's own checks: a suite PR needs no separate approval tickets.

## Checks and reviews

- If a check fails, read its log, fix the cause and push. Re-run a check once only when its log shows an
  infrastructure failure, and say so in the PR.
- Answer every review comment, with a commit that addresses it or a short reason you disagree.
- Never approve your own PR, dismiss a review, push to `main`, push to another repository's branch, or change branch
  protection.

**Merging (suite repositories only):** you may merge your own PR once every required check is green, every review thread is answered, and nobody asked to review it first (Sean's rule, 2026-11-08; KAN-278 for hangar). A draft, a PR labelled `needs-owner-review` or one whose body has an `Owner review:` line counts as one somebody asked to review: read all three first (`gh pr view <n> --json isDraft,labels,body`), and never merge such a PR or turn on auto-merge for it; Sean does. Squash and delete the branch: `gh pr merge <n> --squash --delete-branch`. In a hangar job, hangar lands it. Never use `--admin`, never bypass branch protection, and never merge a PR you were told to leave for review. The merge moves the ticket to Done.
