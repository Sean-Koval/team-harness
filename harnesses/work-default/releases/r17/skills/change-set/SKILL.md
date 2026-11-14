---
name: change-set
description: Use when a ticket's change spans more than one of a service's repositories (infra, database, code, deploy), or when the workspace has several checkouts under /workspace/<role>. Plans which roles change, keeps each repo deployable on its own while the others land, and writes the cross-repo notes the PRs need.
---

# Changes across a service's repositories

A change set is one ticket, one sandbox and one pull request per changed repository. hangar cloned each role to
`/workspace/<role>`, and lands the PRs in the profile's `land_order` (for example database, then infra, then code),
each only after the one before it merged and after its own approvers approve. The deploy repo is bumped last, by a
step that runs no agent. Your job is to make that order safe.

## 1. Decide which roles change

List the roles and say for each one: changes, or no change and why. Change a role only if the ticket needs it. A role
with no diff gets no PR and doesn't hold up the others.

| The ticket needs | Usually changes |
| --- | --- |
| A new table, column or index | database (a migration), then code that uses it |
| A queue, bucket, topic, service account or permission | infra, then code that uses it |
| Only behaviour | code |
| A new environment variable the code reads | infra or deploy config; ask whether the deploy repo owns it, and never edit deploy yourself |

## 2. Make each step safe on its own

Every PR merges and deploys on its own, before the next one exists in production. So:

- **Expand, then contract.** A migration adds (a nullable column, a new table) and never drops or renames what the
  running code uses. Removing the old shape is a later ticket, after the code no longer reads it.
- **Infra before use.** Code must not depend on a resource whose infra PR hasn't landed; with `land_order` putting
  infra first, that holds, but keep the code tolerant of the resource being empty or new.
- **Down migrations work.** The database verify runs up, the tests, then down. Write the down step.
- **No cross-repo imports of uncommitted work.** Each repository builds and passes its checks from its own checkout.

## 3. Verify per role

Run each changed repository's own checks in its own checkout (`cd /workspace/<role>`). Typical:

- infra: `terraform fmt -check -recursive && terraform init -backend=false && terraform validate` (never a real
  backend, never `plan` against real state, never `apply`).
- database: the repository's migrate-up, test and migrate-down targets, against the sandbox's own database service
  (localhost or the service's name), never a shared one.
- code: the repository's lint and tests.

hangar runs each repository's policy `verify` again after you finish; a failure in any role fails the set and comes
back to you with the role named.

## 4. Say what depends on what

In your final summary, and in each PR's description (see `github-pr`), write one line per changed role: what changed
and what it needs from the others ("code reads the `retry_at` column from database's migration 0042"). hangar adds the
table of sibling PRs and the `Hangar-Changeset:` trailer itself; don't hand-write PR links.

## Don'ts

- Don't edit `/workspace/deploy`, even to "fix" an image tag: the deploy step does that after everything merged.
- Don't reorder landing by splitting work differently than the ticket needs, and don't ask a person to merge out of
  order.
- Don't change a role's CI, CODEOWNERS or branch protection.
