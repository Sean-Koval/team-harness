---
id: chat-capture-picked-rooms
type: decision
scope: team
status: accepted
date: '2026-11-11'
owner: lead-example
sources:
- id: chat-capture-decision
  resource: inbox/chat-capture-decision.md
  hash: sha256:3733d4cbc7b0c1df001b9761849f20fc43f0fb6dc4e6d4961864152bc8d0a96e
links:
- type: derived_from
  target: chat-capture-decision
title: Chat capture uses picked rooms only
description: Bounds capture cost and keeps unrelated rooms out of extraction
author: agent:claude-opus-5-5
---
# Chat capture uses picked rooms only

> Decided 2026-11-11 (lead-example): chat capture uses picked rooms only.

## Decision

Only the rooms listed in capture.toml are pulled, once a day, as thread lists. Threads shorter than three messages are never sent to a model.
