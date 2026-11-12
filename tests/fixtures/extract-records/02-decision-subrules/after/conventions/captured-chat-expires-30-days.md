---
id: captured-chat-expires-30-days
type: convention
scope: team
status: active
date: '2026-11-11'
owner: lead-example
sources:
- id: chat-capture-decision
  resource: inbox/chat-capture-decision.md
  hash: sha256:3733d4cbc7b0c1df001b9761849f20fc43f0fb6dc4e6d4961864152bc8d0a96e
links:
- type: derived_from
  target: chat-capture-decision
- type: implements
  target: chat-capture-picked-rooms
title: Captured chat text expires after 30 days
description: Only the records extracted from captured text persist
author: agent:claude-opus-5-5
---
# Captured chat text expires after 30 days

> Captured chat text expires after 30 days; only the records extracted from it persist.

## Rule

Delete captured chat text 30 days after capture; keep only the records.
