---
id: release-notes-from-pr-titles
type: decision
scope: team
status: accepted
date: '2026-11-09'
owner: chidi-example
sources:
- {id: delivery-sync-2026-11-09, resource: team/sources/delivery-sync-2026-11-09.md, hash: "sha256:e08b689e6628394e64251bedb445a33c5aa51277f694c97098b240604d395a2a", quote: 'Then yes. Decided: from the next release on, release notes are generated from PR titles, and we delete the hand-written CHANGELOG.', speaker: chidi-example, at: '00:02:56'}
links:
- {type: derived_from, target: delivery-sync-2026-11-09}
title: Release notes are generated from PR titles
description: The hand-written CHANGELOG is deleted; entries were being missed
author: human:chidi-example
---
# Release notes are generated from PR titles

> 00:02:56 Chidi Obi: Then yes. Decided: from the next release on, release notes are generated from PR titles, and we delete the hand-written CHANGELOG.

## Context

The hand-written CHANGELOG was filled in on release day and missed entries.

## Decision

From the next release, release notes are generated from PR titles, grouped by conventional commit prefix, with
reverts skipped and ticket keys linked. The CHANGELOG file is deleted in the PR that turns the generator on. No
title lint for now.
