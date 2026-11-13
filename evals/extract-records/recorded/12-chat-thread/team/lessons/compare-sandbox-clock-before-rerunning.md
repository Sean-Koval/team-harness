---
id: compare-sandbox-clock-before-rerunning
type: lesson
scope: team
status: open
date: 2026-11-11
owner: eli-example
sources:
  - {id: token-refresh-flake-thread, resource: team/sources/token-refresh-flake-thread.md, hash: "sha256:767c6d5dd93cffb870ff9cf3007be5f5cd40ca516416cf4b17f6fefc561bc674"}
links:
  - {type: derived_from, target: token-refresh-flake-thread}
title: Check the sandbox clock against the host before rerunning a time-based flake
description: Clock skew after snapshot restore cost about two weeks of reruns
author: agent:claude-opus-5-5
---
# Check the sandbox clock against the host before rerunning a time-based flake

> "Lesson: when a time-based test flakes only in sandbox jobs, compare the sandbox clock with the host (`date -u` in both) before rerunning anything. We lost about two weeks rerunning this one." ([09:41] Eli Marsh, edited: "We lost about two weeks rerunning and staring at the mock server.")

## What happened

test_token_refresh failed 10 times in two weeks, only in sandbox jobs. Sandboxes take their clock from the host at boot only, and snapshots restore without a reboot. A fresh restore of the snapshot behind job 4411 was 3m12s behind the host; the test tolerates 60s, which is the real production refresh window. The test was right the whole time.

## What to do next time

When a time-based test flakes only in sandbox jobs, run `date -u` in the sandbox and on the host and compare them before rerunning anything.
