---
id: sandbox-clock-source
type: question
scope: team
status: answered
date: '2026-11-11'
owner: ana-example
sources:
- id: token-refresh-flake-thread
  resource: team/sources/token-refresh-flake-thread.md
  hash: sha256:767c6d5dd93cffb870ff9cf3007be5f5cd40ca516416cf4b17f6fefc561bc674
  quote: '@Ana Reyes quick q, do you know if the sandbox clock is synced from the host or via NTP? I couldn''t find it in the image docs'
  speaker: Dana Kowal
  at: '2026-11-11T09:09:00+00:00'
links:
- {type: derived_from, target: token-refresh-flake-thread}
title: How is the sandbox clock synced?
description: From the host at boot only, so a restored snapshot keeps its old time
author: human:dana-example
---
# How is the sandbox clock synced?

> [09:09] Dana Kowal: @Ana Reyes quick q, do you know if the sandbox clock is synced from the host or via NTP? I couldn't find it in the image docs

## Why it matters

Time-based tests fail when the sandbox clock is behind the host.

## Answer

> [09:14] Ana Reyes: From the host, at boot, and that's it. Nothing re-syncs it during the job. The image has no NTP client, on purpose, since egress is closed

A restored snapshot keeps the time it was taken at until the next boot.
