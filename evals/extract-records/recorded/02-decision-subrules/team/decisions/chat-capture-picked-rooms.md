---
id: chat-capture-picked-rooms
type: decision
scope: team
status: accepted
date: '2026-11-11'
owner: lead-example
sources:
- {id: chat-capture-decision, resource: team/sources/chat-capture-decision.md, hash: "sha256:3733d4cbc7b0c1df001b9761849f20fc43f0fb6dc4e6d4961864152bc8d0a96e"}
links:
- {type: derived_from, target: chat-capture-decision}
title: Chat capture uses picked rooms only
description: Only rooms listed in capture.toml are pulled, daily, as thread lists
author: agent:claude-opus-5-5
---
# Chat capture uses picked rooms only

> Decided 2026-11-11 (lead-example): chat capture uses picked rooms only.

## Decision

Chat capture uses picked rooms only:

- Only the rooms listed in capture.toml are pulled, once a day, as thread lists.
- Threads shorter than three messages are never sent to a model.
- Captured chat text expires after 30 days; only the records extracted from it persist.

## Consequences

The retention rule is also a standing convention: captured-chat-expires-30-days.
