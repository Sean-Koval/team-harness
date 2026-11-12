---
id: chat-capture-decision
type: source
scope: team
status: raw
date: '2026-11-11'
owner: lead-example
sources:
- resource: https://example.invalid/notes/chat-capture-decision
  hash: sha256:3733d4cbc7b0c1df001b9761849f20fc43f0fb6dc4e6d4961864152bc8d0a96e
links: []
description: Chat capture decision
schema_version: 1
revision: '1'
provider: notes
title: Chat capture decision
observed_at: '2026-11-11T10:00:00+00:00'
obligations: []
---
Decided 2026-11-11 (lead-example): chat capture uses picked rooms only.
- Only the rooms listed in capture.toml are pulled, once a day, as thread lists.
- Threads shorter than three messages are never sent to a model.
- Captured chat text expires after 30 days; only the records extracted from it persist.
