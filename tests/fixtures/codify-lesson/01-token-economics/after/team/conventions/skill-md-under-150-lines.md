---
id: skill-md-under-150-lines
type: convention
scope: team
status: active
date: '2026-11-13'
owner: lead-example
sources:
  - {id: LES-0004, resource: team/lessons/LES-0004.md}
  - {resource: 'https://traces.example.invalid/review/2026-11-02'}
links:
  - {type: implements, target: DEC-0031}
title: A skill's SKILL.md stays under 150 lines
description: Every session pays for a skill's full length, so examples and tables live in files it names
domain: harness
author: agent:example-model
---
# A skill's SKILL.md stays under 150 lines

## Rule

A shared skill's `SKILL.md` is under 150 lines. Worked examples and reference tables go in files beside it that
the skill names, and a session reads them only when it needs them.

## Why

Lesson LES-0004: across 12 runs, the three skills over 300 lines cost about 9,400 input tokens a session, and
agents used one section each. Moving one skill's examples into a separate file cut its share to 2,100 tokens with
no change in outcome.

## Examples

- Follows it: `plan-to-tickets/SKILL.md` keeps the ticket layout and points at `examples/` for a full run.
- Breaks it: a 320-line `SKILL.md` with three worked transcripts inline.
