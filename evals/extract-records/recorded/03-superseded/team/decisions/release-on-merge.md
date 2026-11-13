---
id: release-on-merge
type: decision
scope: team
status: accepted
date: '2026-11-12'
owner: lead-example
sources:
- {id: release-review-2026-11-12, resource: team/sources/release-review-2026-11-12.md, hash: "sha256:0913d524666d5890b0ffe332b975809650955db1455eaeb0271f39fe909b85ee"}
links:
- {type: derived_from, target: release-review-2026-11-12}
- {type: supersedes, target: weekly-release-train}
title: Each service releases when its PR merges
description: Replaces the weekly Monday release train
author: agent:claude-opus-5-5
---
# Each service releases when its PR merges

> [00:01:00] lead-example: We are dropping the weekly release train. From today each service releases when its PR merges.

## Context

The weekly release train released every service together each Monday.

## Decision

From 2026-11-12 each service releases when its PR merges. The Friday merge freeze is dropped; release notes in the PR still stand.

## Consequences

The weekly release train is superseded and the Friday merge freeze retired.
