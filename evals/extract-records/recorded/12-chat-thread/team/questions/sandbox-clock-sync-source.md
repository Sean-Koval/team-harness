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
title: Is the sandbox clock synced from the host or via NTP?
description: Not in the image docs; the answer explained the token-refresh flake
author: agent:claude-opus-5-5
---
# Is the sandbox clock synced from the host or via NTP?

> "@Ana Reyes quick q, do you know if the sandbox clock is synced from the host or via NTP? I couldn't find it in the image docs" ([09:09] Dana Kowal)

## Why it matters

The token-refresh test failed only in sandbox jobs and looked time-dependent; how the clock is set decides whether it can drift during a job.

## Answer

> "From the host, at boot, and that's it. Nothing re-syncs it during the job. The image has no NTP client, on purpose, since egress is closed" ([09:14] Ana Reyes)
>
> "and a restored snapshot keeps whatever time it had when the snapshot was taken, until the next boot" ([09:14] Ana Reyes)
