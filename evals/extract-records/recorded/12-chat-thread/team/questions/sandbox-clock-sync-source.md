---
id: sandbox-clock-sync-source
type: question
scope: team
status: answered
date: '2026-11-11'
owner: ana-example
sources:
  - {id: token-refresh-flake-thread, resource: team/sources/token-refresh-flake-thread.md, hash: "sha256:767c6d5dd93cffb870ff9cf3007be5f5cd40ca516416cf4b17f6fefc561bc674"}
links:
  - {type: derived_from, target: token-refresh-flake-thread}
title: Is the sandbox clock synced from the host or via NTP?
description: "Answer: from the host at boot only, so a restored snapshot keeps a stale clock"
author: agent:claude-opus-5-5
---
# Is the sandbox clock synced from the host or via NTP?

> @Ana Reyes quick q, do you know if the sandbox clock is synced from the host or via NTP?

(Dana Kowal, 09:09)

## Why it matters

The token-refresh test failed ten times in two weeks, only in sandbox jobs; a skewed clock would explain it.

## Answer

> From the host, at boot, and that's it. Nothing re-syncs it during the job. The image has no NTP client, on purpose, since egress is closed

> and a restored snapshot keeps whatever time it had when the snapshot was taken, until the next boot

(Ana Reyes, 09:14)
