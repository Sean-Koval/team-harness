---
id: compare-sandbox-clock-before-rerunning
type: lesson
scope: team
status: open
date: '2026-11-11'
owner: eli-example
sources:
- id: token-refresh-flake-thread
  resource: team/sources/token-refresh-flake-thread.md
  hash: sha256:767c6d5dd93cffb870ff9cf3007be5f5cd40ca516416cf4b17f6fefc561bc674
links:
- {type: derived_from, target: token-refresh-flake-thread}
title: Check sandbox clock against host before rerunning a sandbox-only time-based flake
description: About two weeks went to reruns and the mock server before clock skew was found
author: agent:claude-opus-5-5
---
# Check sandbox clock against host before rerunning a sandbox-only time-based flake

> "writing this down before we forget it. Lesson: when a time-based test flakes only in sandbox jobs, compare the sandbox clock with the host (`date -u` in both) before rerunning anything." ([09:41] Eli Marsh; edited: "We lost about two weeks rerunning and staring at the mock server.")

## What happened

test_token_refresh failed ten times in two weeks, only in sandbox jobs. The cause was clock skew after snapshot restore, found by comparing `date -u` in a fresh restore with the host (3m12s behind).

## Next time

When a time-based test flakes only in sandbox jobs, compare the sandbox clock with the host (`date -u` in both) before rerunning anything.
