---
name: github-pr
description: Use when finishing work that becomes a pull request, when writing a PR description, or when answering review comments. Covers who opens the PR on each surface, the title and body contract the PR check enforces, and what never to do on GitHub.
---

# Pull requests

One ticket, one branch, one PR. Everything is reviewed in GitHub, and the work-system PR check fails a PR that breaks
the contract below, whichever surface opened it.

## Who opens it

- **In a hangar job:** hangar pushes and opens the PR as its GitHub App, with the key in the branch and title. You
  end your turn with the description below; don't open PRs yourself.
- **In a local or cloud session:** push the branch and open the PR yourself with
  `gh pr create --draft --title '<KEY>: <what changes>' --body-file <file>`, ready for review once the repository's
  checks pass. In a cloud session whose branch name was assigned, keep it: the title and `Jira:` line link the PR.

## The contract

- **Title:** `<KEY>: <what changes>`, under 72 characters.
- **Body**, the repository's PR template when it has one, otherwise in this order:
  - `Jira: <KEY>` on its own line (the same key as the title)
  - `Docs: <files or Confluence page you updated, or "none needed - why">` (`work-docs`)
  - `Decision: <KEY>` only when the PR implements a Decision that binds code; it then adds the ADR
  - **What and why:** two to five lines
  - **How it was verified:** the commands you ran and their result
  - **Risk and rollout**, and **Not done** with the reason for anything in the ticket you left out

## Checks and reviews

- If a check fails, read its log, fix the cause and push. Re-run a check once only when its log shows an
  infrastructure failure, and say so in the PR.
- Answer every review comment, with a commit that addresses it or a short reason you disagree.
- Never merge, approve your own PR, dismiss a review, enable auto-merge, push to `main` or change branch protection.
  Merges are Sean's (or the adopted auto-merge rule's), and the merge moves the ticket to Done.
