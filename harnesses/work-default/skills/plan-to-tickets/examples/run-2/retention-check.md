---
summary: "ai-dlc: `knowledge check` warns about sources that expire within 7 days"
labels: [proposed, "repo:ai-dlc", "exec:pair"]
links:
  - {type: implements, target: DEC-0042}
  - {type: is blocked by, target: ABC-301}
parent: ABC-200
filed_as: ABC-302
---
## Goal

Nobody loses a transcript they meant to extract: the check names sources about to expire.

**Repo:** ai-dlc
**Start after:** ABC-301
**PR base:** main. Open the PR against main, never against another feature branch. If the work needs an
unmerged PR, branch from that PR's branch, still target main, and write "depends on #<n>" in the PR body.

## What changes

* `knowledge check` prints one warning per `inbox/` source within 7 days of expiry.
* The warning never fails the check.

## Acceptance criteria

* A fixture source captured 25 days ago produces exactly one warning, and the exit code stays 0.
* flightdeck check `never-push-main` holds: `{never: {tool: {kind: shell, ops: [git.push]}, where: {input: {regex: "\\b(main|master)\\b"}}}}`
* The PR's base branch is main.

## Verify

`ai-dlc project check --required`

## Out of scope

deleting files (retention-job).

## Governing spec

Decision DEC-0042 (team/decisions/DEC-0042.md).

Plan item: DEC-0042#retention-check
