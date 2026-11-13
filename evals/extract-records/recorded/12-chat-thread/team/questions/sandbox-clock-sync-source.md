---
id: sandbox-clock-sync-source
type: question
scope: team
status: answered
date: 2026-11-11
owner: ana-example
sources:
  - {id: token-refresh-flake-thread, resource: team/sources/token-refresh-flake-thread.md, hash: "sha256:767c6d5dd93cffb870ff9cf3007be5f5cd40ca516416cf4b17f6fefc561bc674"}
links:
  - {type: derived_from, target: token-refresh-flake-thread}
  - {type: belongs_to, target: PLAT-433}
title: Is the sandbox clock synced from the host or via NTP?
description: The answer explained the token-refresh flake: restored snapshots keep a stale clock
author: agent:claude-opus-5-5
---
# Is the sandbox clock synced from the host or via NTP?

> "@Ana Reyes quick q, do you know if the sandbox clock is synced from the host or via NTP?" ([09:09] Dana Kowal)

## Why it matters

The token-refresh test failed only in sandbox jobs and looked time-related; the image docs did not say how the clock is set.

## Answer

> "From the host, at boot, and that's it." ([09:14] Ana Reyes)

Nothing re-syncs it during the job; the image has no NTP client because egress is closed, and a restored snapshot keeps its old time until the next boot.
