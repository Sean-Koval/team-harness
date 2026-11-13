---
id: check-sandbox-clock-before-rerunning
type: lesson
scope: team
status: open
date: 2026-11-11
owner: eli-example
sources:
  - {id: token-refresh-flake-thread, resource: team/sources/token-refresh-flake-thread.md, hash: "sha256:767c6d5dd93cffb870ff9cf3007be5f5cd40ca516416cf4b17f6fefc561bc674"}
links:
  - {type: derived_from, target: token-refresh-flake-thread}
  - {type: belongs_to, target: PLAT-433}
title: Compare sandbox and host clocks before rerunning a time-based flake
description: About two weeks went to reruns before clock skew was found
author: agent:claude-opus-5-5
---
# Compare sandbox and host clocks before rerunning a time-based flake

> "Lesson: when a time-based test flakes only in sandbox jobs, compare the sandbox clock with the host (`date -u` in both) before rerunning anything." ([09:41] Eli Marsh)

## What happened

test_refresh_before_expiry failed ten times in two weeks, only in sandbox jobs. Restored snapshots keep the clock from when they were taken; a fresh restore was 3m12s behind the host, while the test tolerates 60s. The team lost about two weeks rerunning and looking at the mock server.

## What to do next time

When a time-based test flakes only in sandbox jobs, run `date -u` in the sandbox and on the host and compare before rerunning anything.
