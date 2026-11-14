---
id: resync-clock-after-snapshot-restore
type: action
scope: team
status: open
date: '2026-11-11'
owner: dana-example
sources:
- id: token-refresh-flake-thread
  resource: team/sources/token-refresh-flake-thread.md
  hash: sha256:767c6d5dd93cffb870ff9cf3007be5f5cd40ca516416cf4b17f6fefc561bc674
  quote: I'll add that to the restore script, PR by Friday
  speaker: Dana Kowal
  at: '2026-11-11T09:37:00+00:00'
- resource: https://git.example.invalid/platform/sandbox-image/pull/88
links:
  - {type: derived_from, target: token-refresh-flake-thread}
title: Resync the sandbox clock from the host after a snapshot restore
description: Fixes the token-refresh flake caused by clock skew of up to hours after restore
stale_after: '2026-11-13T00:00:00Z'
author: agent:claude-opus-5-5
---
# dana-example adds a clock resync to the restore script

> I'll add that to the restore script, PR by Friday

(Dana Kowal, 09:37; the fix: "resync the clock from the host as the first step after a snapshot restore")

## Done when

The restore script resyncs the clock from the host as its first step after a snapshot restore, and the PR is merged. A draft PR was opened at 10:12 (sandbox-image#88), tagged for ana-example's review; it should mention the 4-hour snapshot refresh interval.
