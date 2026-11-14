---
id: compare-sandbox-clock-before-rerunning
type: lesson
scope: team
status: open
date: '2026-11-11'
owner: eli-example
sources:
  - {id: token-refresh-flake-thread, resource: team/sources/token-refresh-flake-thread.md, hash: "sha256:767c6d5dd93cffb870ff9cf3007be5f5cd40ca516416cf4b17f6fefc561bc674"}
links:
  - {type: derived_from, target: token-refresh-flake-thread}
title: Check the sandbox clock against the host when a time-based test flakes only in sandboxes
description: About two weeks went on reruns and the mock server before clock skew after restore was found
author: agent:claude-opus-5-5
---
# Compare the sandbox clock with the host before rerunning

> Lesson: when a time-based test flakes only in sandbox jobs, compare the sandbox clock with the host (`date -u` in both) before rerunning anything.

(Eli Marsh, 09:41)

## What happened

The token-refresh test failed ten times in two weeks, only in sandbox jobs. The sandbox clock is set from the host at boot only, and snapshots restore without a reboot; a fresh restore was 3m12s behind the host while the test tolerates 60s. "We lost about two weeks rerunning and staring at the mock server." (Eli Marsh, 09:41, edited)

## What to do next time

When a time-based test flakes only in sandbox jobs, run `date -u` in the sandbox and on the host and compare them before rerunning anything.
