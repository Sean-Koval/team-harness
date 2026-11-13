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
description: The hand-written file was only filled in on release day and missed entries customers then found
author: agent:claude-opus-5-5
---
# Release notes are generated from PR titles; the hand-written CHANGELOG goes

> "Decided: from the next release on, release notes are generated from PR titles, and we delete the hand-written CHANGELOG." (00:02:56, Chidi Obi)

## Context

Nobody updated the hand-written CHANGELOG until release day; the last release missed two entries and the support desk heard of them from a customer. The generator is already in the repo template, unused. Ana Reyes: "Chidi, it's your call, you own releases."

## Options considered

- Keep hand-writing the CHANGELOG.
- Generate notes from PR titles grouped by conventional commit prefix. A PR-title lint check was raised and deferred: "Let's see how bad it is first." (Chidi Obi, 00:02:33)

## Decision

From the next release on, release notes are generated from PR titles, grouped by conventional commit prefix (feat, fix, ...). The generator skips a revert and the PR it reverted when both are in the same release, and keeps the ticket key in the title and links it. The hand-written CHANGELOG is deleted in the same PR that turns the generator on; git keeps its history. No title lint check for now.

## Consequences

- PR title quality shows directly in the release notes.
- The one-approval-before-merge rule is unchanged by the generator.
