---
id: pin-harness-by-digest
type: decision
scope: team
status: accepted
date: '2026-11-10'
owner: lead-example
sources:
- id: release-sync-2026-11-10
  resource: team/sources/release-sync-2026-11-10.md
  hash: sha256:38e203e8591036d3b6c7611f26da52253ff549a458e37c2a2927b6932e2b0ef6
  quote: Every job pins the harness by digest, not by channel name.
  speaker: dev-example
  at: '00:04:30'
links:
- type: derived_from
  target: release-sync-2026-11-10
title: Jobs pin the harness by digest
description: A channel can move under a running job; a digest cannot
author: agent:claude-opus-5-5
---
# Jobs pin the harness by digest

> [00:04:30] dev-example: Every job pins the harness by digest, not by channel name.

## Decision

Every job names its harness by digest, never by channel name.
