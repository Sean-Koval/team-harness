---
id: resync-clock-on-snapshot-restore
type: action
scope: team
status: open
date: '2026-11-11'
owner: dana-example
sources:
- {id: token-refresh-flake-thread, resource: team/sources/token-refresh-flake-thread.md, hash: "sha256:767c6d5dd93cffb870ff9cf3007be5f5cd40ca516416cf4b17f6fefc561bc674"}
links:
- {type: derived_from, target: token-refresh-flake-thread}
title: Resync the sandbox clock after a snapshot restore
description: Fixes the token-refresh flake at its cause instead of loosening the test
stale_after: '2026-11-13T00:00:00Z'
author: human:dana-example
---
# dana-example adds a clock resync to the restore script

> [09:37] Dana Kowal: ok back to the clock. fix is simple: resync the clock from the host as the first step after a snapshot restore. I'll add that to the restore script, PR by Friday

## Done when

The restore script resyncs the clock from the host as its first step after a snapshot restore.
