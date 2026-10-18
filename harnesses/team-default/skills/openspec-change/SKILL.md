---
name: openspec-change
description: Use when a ticket changes behaviour (an API, a user-visible flow, a data contract) and the repository uses OpenSpec (an `openspec/` directory). Proposes, specifies, implements and archives one OpenSpec change.
---

# Spec-driven change with OpenSpec

OpenSpec keeps the agreed behaviour in `openspec/specs/` and each proposed change in `openspec/changes/<id>/`
(`proposal.md`, `tasks.md`, optional `design.md`, and spec deltas under `specs/`). Use the `openspec` CLI the
repository pins; if it isn't installed, say so and stop rather than hand-writing the layout.

## When to use it

- Use it for new or changed behaviour, breaking changes, and anything a reviewer would want to agree on before the
  code exists.
- Skip it for a bug fix that restores specified behaviour, a dependency bump, formatting, or tests for existing
  behaviour. Say in the PR why no change was needed.

## Steps

1. **Look first.** `openspec list` and `openspec list --specs` to see open changes and current capabilities. If an
   open change already covers the ticket, continue it instead of starting another.
2. **Propose.** Pick a kebab-case, verb-led id (`add-export-endpoint`). Write `proposal.md` (why, what changes,
   impact), `tasks.md` (a checklist you will tick as you go) and the spec deltas: `## ADDED Requirements`,
   `## MODIFIED Requirements` or `## REMOVED Requirements`, each requirement with at least one
   `#### Scenario:` written as WHEN / THEN.
3. **Validate.** `openspec validate <id> --strict` must pass before you write code. Fix the spec, not the validator.
4. **Stop for review when the ticket asks for it.** If the ticket says "spec first", open the PR with the proposal
   only (title prefix `spec:`), and wait.
5. **Implement against the tasks.** Tick each item in `tasks.md` only when its code and tests are in. Tests should
   name the scenario they cover.
6. **Archive on the delivery branch.** Once the implementation is approved, `openspec archive <id> --yes` folds the
   deltas into `openspec/specs/` in the same PR, so the merged specs match the merged code.

## In the pull request

- Link the change directory and list the requirements it adds or modifies.
- Paste the `openspec validate --strict` result.
- If you deviated from the proposal, update the proposal first and say why.
