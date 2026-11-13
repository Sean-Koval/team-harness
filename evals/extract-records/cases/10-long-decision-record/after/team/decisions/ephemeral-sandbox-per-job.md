---
id: ephemeral-sandbox-per-job
type: decision
scope: team
status: accepted
date: '2026-11-05'
owner: ana-example
sources:
- {id: agent-sandbox-decision, resource: team/sources/agent-sandbox-decision.md, hash: "sha256:dfb005bfd5bf729ec1f48e7417fbe16107dc9435f2da05b57364555d7e034595"}
links:
- {type: derived_from, target: agent-sandbox-decision}
- {type: belongs_to, target: PLAT-412}
title: Agent jobs run in ephemeral sandboxes from one pinned image
description: Isolation, identical starts and job-scoped credentials by construction, for about 40% more spend
author: human:ana-example
---
# Agent jobs run in ephemeral sandboxes from one pinned image

> Decided 2026-11-05 by ana-example: agent jobs run in one ephemeral sandbox per job, built from a single base image pinned by digest, and the sandbox is destroyed when the job ends.

## Context

Shared, long-lived runners leaked state between jobs, drifted apart and kept credentials on disk for weeks.

## Options considered

Hardened shared runners (cleanup lists leave gaps), ephemeral sandboxes from a pinned image (chosen), and the CI
vendor's hosted runners (no digest pinning, no per-job egress, over the cost limit).

## Decision

One fresh sandbox per job, destroyed at the end; only the PR, trace and log survive. The base image is pinned by
digest in `sandbox.lock`, never by tag, and rebuilt every Monday and on any security advisory. Egress is denied by
default, with the allowlist beside the image and changed only by PR. Credentials are per-job tokens scoped to one
repository. Jobs time out at 45 minutes and are not retried. The shared runners are drained on 2026-11-12 and
deleted a week later.

## Consequences

About 90 seconds more cold start and about 40% more monthly spend; the team owns the image build and allowlist.
