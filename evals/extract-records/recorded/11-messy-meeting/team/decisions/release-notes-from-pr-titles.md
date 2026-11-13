---
id: release-notes-from-pr-titles
type: decision
scope: team
status: accepted
date: 2026-11-09
owner: chidi-example
sources:
  - {id: delivery-sync-2026-11-09, resource: team/sources/delivery-sync-2026-11-09.md, hash: "sha256:e08b689e6628394e64251bedb445a33c5aa51277f694c97098b240604d395a2a"}
links:
  - {type: derived_from, target: delivery-sync-2026-11-09}
title: Release notes are generated from PR titles; the hand-written CHANGELOG goes
description: Hand-written entries were missed on release day and reached customers before support
author: agent:claude-opus-5-5
---
# Release notes are generated from PR titles

> "Decided: from the next release on, release notes are generated from PR titles, and we delete the hand-written CHANGELOG." (00:02:56, Chidi Obi)

## Context

Nobody updated the hand-written CHANGELOG until release day; the last release missed two entries and the support desk learned of them from a customer.

## Options considered

- Keep hand-writing the CHANGELOG.
- Generate notes from PR titles with the generator already in the repo template (chosen).
- Lint PR titles with a check: deferred, no new gate on day one.

## Decision

From the next release on, release notes are generated from PR titles, grouped by conventional commit prefix. Reverts and the PR they revert are skipped when both are in the same release. Ticket keys in titles are kept and linked. Chidi turns the generator on and deletes the CHANGELOG in the same PR; git keeps its history.

## Consequences

Bad PR titles show up in the notes. Every PR still needs one approval before merge (unchanged).
