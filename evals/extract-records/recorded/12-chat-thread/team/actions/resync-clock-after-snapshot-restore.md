---
id: resync-clock-after-snapshot-restore
type: action
scope: team
status: open
date: 2026-11-11
owner: dana-example
sources:
  - {id: token-refresh-flake-thread, resource: team/sources/token-refresh-flake-thread.md, hash: "sha256:767c6d5dd93cffb870ff9cf3007be5f5cd40ca516416cf4b17f6fefc561bc674"}
  - {resource: "https://git.example.invalid/platform/sandbox-image/pull/88"}
links:
  - {type: derived_from, target: token-refresh-flake-thread}
title: Resync the sandbox clock from the host right after a snapshot restore
description: Snapshots restore without a reboot, leaving the clock minutes behind and failing the token-refresh test
stale_after: 2026-11-13T00:00:00Z
author: agent:claude-opus-5-5
---
# Who owes what

> "fix is simple: resync the clock from the host as the first step after a snapshot restore. I'll add that to the restore script, PR by Friday" ([09:37] Dana Kowal)

dana-example owes the restore-script change; ana-example asked to be tagged on it. A draft PR was opened at [10:12] (sandbox-image#88). The PR should also mention the 4-hour snapshot refresh interval ([09:52] Dana Kowal).

## Done when

The restore script resyncs the clock from the host as its first step after a snapshot restore, and the PR is merged.
