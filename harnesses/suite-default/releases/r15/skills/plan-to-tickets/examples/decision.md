---
id: DEC-0042
aliases: [expire-raw-sources]
type: decision
scope: team
status: accepted
date: 2026-11-10
owner: example-owner
sources:
  - {id: SRC-0107, resource: team/sources/SRC-0107.md}
links:
  - {type: derived_from, target: SRC-0107}
  - {type: belongs_to, target: ABC-200}
title: Raw inbox sources expire after 30 days
description: Transcripts are kept only until their records are reviewed, so the inbox never becomes an archive
domain: tooling
checks:
  - id: never-push-main
    assert: {never: {tool: {kind: shell, ops: [git.push]}, where: {input: {regex: "\\b(main|master)\\b"}}}}
---
# Raw inbox sources expire after 30 days

## Context

Captured transcripts wait in the knowledge repository's `inbox/` until extraction. Nothing removes them.

## Options considered

1. Keep them forever. 2. Expire them after 30 days. 3. Delete them at extraction.

## Decision

Option 2: a raw source in `inbox/` is deleted 30 days after capture; processed copies under the checked roots stay.

## Consequences

Extraction must happen within 30 days, and the check warns before a source expires.

## Plan

### retention-job

Summary: delete inbox sources 30 days after capture
Goal: The inbox holds no raw source older than 30 days, without anyone deleting files by hand.
Repo: knowledge
Start after: none
What changes:
- A scheduled workflow that deletes `inbox/` files whose `captured` date is more than 30 days old.
- A dry-run mode that lists what it would delete.
Acceptance:
- On a fixture inbox, files older than 30 days are deleted and newer ones are kept.
- Dry run deletes nothing and lists exactly the expired files.
Verify: `python -m pytest -q tests/test_retention.py`
Out of scope: warning before expiry (retention-check).
Exec: pair

### retention-check

Summary: `knowledge check` warns about sources that expire within 7 days
Goal: Nobody loses a transcript they meant to extract: the check names sources about to expire.
Repo: ai-dlc
Start after: retention-job
What changes:
- `knowledge check` prints one warning per `inbox/` source within 7 days of expiry.
- The warning never fails the check.
Acceptance:
- A fixture source captured 25 days ago produces exactly one warning, and the exit code stays 0.
Verify: `ai-dlc project check --required`
Out of scope: deleting files (retention-job).
Exec: agent

### retention-notice

Summary: tell people before their sources expire
Goal: People hear about expiring sources where they work.
Repo: team-harness and work-copilot
What changes:
- A reminder in the session-end hook and in the copilot digest.
Verify: check by hand that the reminder shows up
