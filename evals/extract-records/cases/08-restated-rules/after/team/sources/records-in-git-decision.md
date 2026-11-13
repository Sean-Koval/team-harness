---
id: records-in-git-decision
type: source
scope: team
status: processed
date: '2026-11-12'
owner: lead-example
sources:
- resource: https://example.invalid/wiki/records-in-git-decision
  hash: sha256:4694a83ca8368a9a2ca359d22e65e9a580da29c6b282982bcb5a549f2fc1467d
links: []
description: 'Decision: records in git'
schema_version: 1
revision: '1'
provider: wiki
title: 'Decision: records in git'
observed_at: '2026-11-12T12:00:00+00:00'
obligations: []
---
Outcome: Decided 2026-11-12 by lead-example. Knowledge records live as files in git; the wiki is rendered from them.

## Details
- Records are files in git, one file per record, under team/, personal/ or projects/<name>/.
- The wiki is a rendered copy; the render job is its only writer.
- Agents propose records only as a draft PR that a person merges.

## Rules (restated from the details above)
- Never edit the wiki by hand.
- Records change only through a reviewed PR.
- One file per record.

## Follow-ups
- Prerequisite: the render job needs its own service account before go-live.
