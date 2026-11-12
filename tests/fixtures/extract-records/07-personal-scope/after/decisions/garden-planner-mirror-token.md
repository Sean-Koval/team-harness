---
id: garden-planner-mirror-token
type: decision
scope: personal
status: accepted
date: '2026-11-09'
owner: lead-example
sources:
- id: garden-planner-auth-page
  resource: inbox/garden-planner-auth-page.md
  hash: sha256:0ce0f4cd6f02c7aa2920e1788482282f6b0a30947b6757f57975a2f3ade6aee0
links:
- type: derived_from
  target: garden-planner-auth-page
- type: belongs_to
  target: garden-planner
title: garden-planner's mirror uses a dedicated scoped token
description: A leaked token reaches only the mirror's project, not the owner's account
author: agent:claude-opus-5-5
---
# garden-planner's mirror uses a dedicated scoped token

> Comment (2026-11-09, lead-example): Decided: A.

## Options considered

A. a dedicated account with a scoped token. B. the owner's personal token.

## Decision

A.
