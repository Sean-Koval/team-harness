---
id: release-notes-from-pr-titles
type: decision
scope: team
status: accepted
date: '2026-11-09'
owner: chidi-example
sources:
  - {id: delivery-sync-2026-11-09, resource: team/sources/delivery-sync-2026-11-09.md, hash: "sha256:e08b689e6628394e64251bedb445a33c5aa51277f694c97098b240604d395a2a"}
links:
  - {type: derived_from, target: delivery-sync-2026-11-09}
title: Release notes are generated from PR titles; the hand-written CHANGELOG goes
description: Ends missed entries on release day; PR titles now feed customer-facing notes
author: agent:claude-opus-5-5
---
# Release notes are generated from PR titles

> Decided: from the next release on, release notes are generated from PR titles, and we delete the hand-written CHANGELOG.

(Chidi Obi, 00:02:56)

## Context

Nobody updated the hand-written CHANGELOG until release day, and the last release missed two entries that the support desk heard about from a customer. The generator is already in the repo template but was never turned on. Chidi Obi owns releases.

## Options considered

- Keep hand-writing the CHANGELOG.
- Generate notes from PR titles, grouped by conventional commit prefix: chosen.
- A lint check on PR titles: not now; see how bad titles are first.

## Decision

- From the next release on, release notes are generated from PR titles, grouped by conventional commit prefix (feat, fix and so on).
- The hand-written CHANGELOG is deleted in the same PR that turns the generator on; git keeps its history.
- The generator skips a revert and the PR it reverted when both are in the same release.
- The generator keeps the ticket key from the title and links it, so the notes link back to the ticket.
- No PR-title lint check for now.

## Consequences

- PR titles become customer-visible; a bad title shows up in the notes.
- Every PR still needs one approval before merge (unchanged).
