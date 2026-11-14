---
id: check-sandbox-clock-first
type: lesson
scope: team
status: open
date: '2026-11-11'
owner: eli-example
sources:
- {id: token-refresh-flake-thread, resource: team/sources/token-refresh-flake-thread.md, hash: "sha256:767c6d5dd93cffb870ff9cf3007be5f5cd40ca516416cf4b17f6fefc561bc674", quote: 'writing this down before we forget it. Lesson: when a time-based test flakes only in sandbox jobs, compare the sandbox clock with the host (`date -u` in both) before rerunning anything. We lost about two weeks rerunning this one.', speaker: eli-example, at: '2026-11-11T09:41:00+00:00'}
links:
- {type: derived_from, target: token-refresh-flake-thread}
title: Check the sandbox clock before rerunning a time-based flake
description: Two weeks of reruns traced to a sandbox clock 3m12s behind the host
author: human:eli-example
---
# Check the sandbox clock before rerunning a time-based flake

> [09:41] Eli Marsh: writing this down before we forget it. Lesson: when a time-based test flakes only in sandbox jobs, compare the sandbox clock with the host (`date -u` in both) before rerunning anything. We lost about two weeks rerunning this one.

## What happened

The token-refresh test failed ten times in two weeks, only in sandbox jobs. Restored snapshots kept an old clock.

## What to do next time

When a time-based test flakes only in sandbox jobs, compare `date -u` in the sandbox and on the host first.
