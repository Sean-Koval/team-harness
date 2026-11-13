---
summary: "knowledge: delete inbox sources 30 days after capture"
labels: [proposed, "repo:knowledge", "exec:pair"]
links:
  - {type: implements, target: DEC-0042}
parent: ABC-200
filed_as: ABC-301
---
## Goal

The inbox holds no raw source older than 30 days, without anyone deleting files by hand.

**Repo:** knowledge
**Start after:** none
**PR base:** main. Open the PR against main, never against another feature branch. If the work needs an
unmerged PR, branch from that PR's branch, still target main, and write "depends on #<n>" in the PR body.

## What changes

* A scheduled workflow that deletes `inbox/` files whose `captured` date is more than 30 days old.
* A dry-run mode that lists what it would delete.

## Acceptance criteria

* On a fixture inbox, files older than 30 days are deleted and newer ones are kept.
* Dry run deletes nothing and lists exactly the expired files.
* flightdeck check `never-push-main` holds: `{never: {tool: {kind: shell, ops: [git.push]}, where: {input: {regex: "\\b(main|master)\\b"}}}}`
* The PR's base branch is main.

## Verify

`python -m pytest -q tests/test_retention.py`

## Out of scope

warning before expiry (retention-check).

## Governing spec

Decision DEC-0042 (team/decisions/DEC-0042.md).

Plan item: DEC-0042#retention-job
