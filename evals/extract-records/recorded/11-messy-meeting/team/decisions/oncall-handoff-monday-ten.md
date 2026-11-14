---
id: oncall-handoff-monday-ten
type: decision
scope: team
status: accepted
date: '2026-11-09'
owner: ana-example
sources:
  - {id: delivery-sync-2026-11-09, resource: team/sources/delivery-sync-2026-11-09.md, hash: "sha256:e08b689e6628394e64251bedb445a33c5aa51277f694c97098b240604d395a2a", quote: 'Okay, so, to be clear, because I said the other thing a minute ago: decided, on-call handoff is Monday at ten, after standup, starting next Monday the 16th.', speaker: ana-example, at: '00:04:32'}
links:
  - {type: derived_from, target: delivery-sync-2026-11-09}
title: On-call handoff moves to Monday at ten, after standup
description: Ends the collision with standup while keeping everyone around for the incoming on-call; Friday was rejected
valid_from: '2026-11-16'
author: agent:claude-opus-5-5
---
# On-call handoff is Monday at ten, after standup

> Okay, so, to be clear, because I said the other thing a minute ago: decided, on-call handoff is Monday at ten, after standup, starting next Monday the 16th.

(Ana Reyes, 00:04:32)

## Context

Handoff was Monday at 9:30 and collided with standup, so handoff notes came out thin. The rotation is flipped by a manual edit in the pager schedule, and the support desk pages whoever the schedule says.

## Options considered

- Friday at four: briefly agreed earlier in the meeting, then reversed after Eli Marsh pointed out the incoming person would have the weekend with no one to ask, and the support desk is off Friday afternoons since October.
- Monday at ten, after standup: chosen.

## Decision

On-call handoff is Monday at 10:00, after standup, starting Monday 2026-11-16. Friday is off the table. The outgoing person still writes the handoff note (unchanged).

## Consequences

- The pager schedule must be changed so the shift flips Monday at ten.
- The support desk must be told the handoff time changed.
