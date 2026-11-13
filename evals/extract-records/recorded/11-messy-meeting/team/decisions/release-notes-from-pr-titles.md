---
id: release-notes-from-pr-titles
type: decision
scope: team
status: accepted
date: '2026-11-09'
owner: chidi-example
sources:
- id: delivery-sync-2026-11-09
  resource: team/sources/delivery-sync-2026-11-09.md
  hash: sha256:e08b689e6628394e64251bedb445a33c5aa51277f694c97098b240604d395a2a
links:
- {type: derived_from, target: delivery-sync-2026-11-09}
title: Release notes are generated from PR titles; the hand-written CHANGELOG is deleted
description: Hand-written entries were missed at release time and customers found out first
author: agent:claude-opus-5-5
---
# Release notes are generated from PR titles; the hand-written CHANGELOG is deleted

> "Then yes. Decided: from the next release on, release notes are generated from PR titles, and we delete the hand-written CHANGELOG." (00:02:56, Chidi Obi)

## Decision

From the next release on, release notes are generated from PR titles, grouped by conventional commit prefix, using the generator already in the repository template. The hand-written CHANGELOG is deleted in the same PR that turns the generator on (Chidi); git keeps its history.

- Reverts and the PR they revert are skipped when both are in the same release.
- Ticket keys in titles are kept and linked to the ticket.
- No PR-title lint check for now ("Maybe later. I don't want to add a gate on day one.").

## Context

Nobody updated the CHANGELOG until release day; the last release missed two entries and the support desk heard from a customer. Chidi owns releases.
