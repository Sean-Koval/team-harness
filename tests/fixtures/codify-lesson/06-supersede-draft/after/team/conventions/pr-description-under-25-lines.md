---
id: pr-description-under-25-lines
type: convention
scope: team
status: draft
date: '2026-11-13'
owner: lead-example
sources:
  - {id: LES-0021, resource: team/lessons/LES-0021.md}
  - {resource: 'https://traces.example.invalid/review/2026-11-06'}
links: []
title: A PR description stays under 25 lines
description: Reviewers skip longer descriptions, so what was left out comes first
domain: sdlc
author: agent:example-model
---
# A PR description stays under 25 lines

## Rule

A pull request's description is under 25 lines, and says what was left out within its first five lines.

## Why

Lesson LES-0021: of 30 merged pull requests, reviewers asked about something the description already said in 7 of
the 11 that ran 25 to 40 lines, and in 2 of the 19 under 25 lines.

## Examples

- Follows it: an 18-line description whose third line says the migration is left for a later ticket.
- Breaks it: a 35-line description that mentions what was left out in its last line.
