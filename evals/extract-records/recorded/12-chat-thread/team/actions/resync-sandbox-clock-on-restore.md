---
id: resync-sandbox-clock-on-restore
type: action
scope: team
status: open
date: '2026-11-11'
owner: dana-example
stale_after: '2026-11-13'
sources:
- id: token-refresh-flake-thread
  resource: team/sources/token-refresh-flake-thread.md
  hash: sha256:767c6d5dd93cffb870ff9cf3007be5f5cd40ca516416cf4b17f6fefc561bc674
- id: sandbox-image-pr-88
  resource: https://git.example.invalid/platform/sandbox-image/pull/88
links:
- {type: derived_from, target: token-refresh-flake-thread}
title: Resync the sandbox clock from the host right after snapshot restore
description: Restored snapshots keep their old time, which broke the token-refresh test by minutes
author: agent:claude-opus-5-5
---
# Resync the sandbox clock from the host right after snapshot restore

> "ok back to the clock. fix is simple: resync the clock from the host as the first step after a snapshot restore. I'll add that to the restore script, PR by Friday" ([09:37] Dana Kowal)

## Action

Dana adds a host clock resync as the first step after snapshot restore in the restore script, PR by Friday 2026-11-13, tagging Ana. The PR also notes the snapshot refresh interval (every 4 hours, from the restore script header). Draft PR opened at [10:12]: https://git.example.invalid/platform/sandbox-image/pull/88.

## Context

Root cause of the test_token_refresh flake: sandboxes are clock-synced from the host only at boot, the image has no NTP client, and snapshots restore without a reboot; a fresh restore was 3m12s behind the host, while the test tolerates 60 s (the real production refresh window, so the test stays as is). Adding a date check to the job template waits until the resync is proven.
