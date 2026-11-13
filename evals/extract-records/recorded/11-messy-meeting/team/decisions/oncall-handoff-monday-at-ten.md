---
id: oncall-handoff-monday-at-ten
type: decision
scope: team
status: accepted
date: 2026-11-09
owner: ana-example
sources:
  - {id: delivery-sync-2026-11-09, resource: team/sources/delivery-sync-2026-11-09.md, hash: "sha256:e08b689e6628394e64251bedb445a33c5aa51277f694c97098b240604d395a2a"}
links:
  - {type: derived_from, target: delivery-sync-2026-11-09}
title: On-call handoff moves to Monday at ten, after standup
description: Stops the handoff colliding with standup while keeping everyone around for the incoming person
valid_from: 2026-11-16
author: agent:claude-opus-5-5
---
# On-call handoff moves to Monday at ten, after standup

> "decided, on-call handoff is Monday at ten, after standup, starting next Monday the 16th. Friday is off the table." (00:04:32, Ana Reyes)

## Context

Handoff was Monday at nine thirty and collided with standup, so the outgoing person wrote the note while half in standup and the incoming person got a thin note.

## Options considered

- **Friday at four.** Briefly agreed at 00:01:21, then reversed at 00:04:11 after Eli Marsh pointed out the incoming person would have the weekend with no one to ask, and the support desk is off Friday afternoons since October.
- **Monday at ten, after standup.** Keeps the Monday advantage of everyone being around and clears the standup collision.

## Decision

On-call handoff is Monday at 10:00, after standup, starting Monday 2026-11-16. Friday is off the table. The outgoing person still writes the handoff note (unchanged).

## Consequences

- The pager rotation must be edited by hand so the shift flips Monday at ten.
- The support desk pages whoever the schedule says, so it must be told the new time.
