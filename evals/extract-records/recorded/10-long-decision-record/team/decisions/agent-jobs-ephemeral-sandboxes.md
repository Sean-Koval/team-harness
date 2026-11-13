---
id: agent-jobs-ephemeral-sandboxes
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
title: Agent jobs run in ephemeral sandboxes from one pinned base image
description: Isolation, identical start bytes and job-scoped credentials by construction, at about 90s cold start and 40% more spend
valid_from: '2026-11-05'
author: agent:claude-opus-5-5
---
# Agent jobs run in ephemeral sandboxes from one pinned base image

> Decided 2026-11-05 by ana-example: agent jobs run in one ephemeral sandbox per job, built from a single base image pinned by digest, and the sandbox is destroyed when the job ends.

(Outcome, decision owner ana-example, 2026-11-05)

## Context

Since September agent jobs ran on four shared, long-lived runners, a trial that was never a decision. State leaked between jobs, the runners drifted, and credentials stayed on disk for weeks. Job volume is expected to triple by the end of the quarter. Constraints: no job sees another's leftovers; identical start bytes for the same commit; no credential outlives its job; cold start under two minutes; monthly cost grows by at most half.

Scope: agent jobs only (pick up a ticket, work in one repository, open a pull request). Not the CI checks on those PRs, not the nightly docs build, not GPU jobs, not local runs.

## Options considered

- A: keep and harden the shared runners (wipe, weekly rebuild, nightly rotation). Fails the isolation and credential constraints by design.
- B: one ephemeral sandbox per job from a pinned base image. Meets all five constraints; chosen.
- C: the CI vendor's hosted runners. Cannot pin by digest, per-organization egress only, no access to the internal mirror, about 70% more cost. Dropped for now; may be revisited if the vendor ships per-job egress controls and digest pinning (ana-example, review reply).

## Decision

- Each job gets a fresh sandbox. Nothing survives the job except the pull request, the job trace and the job log. A sandbox is never reused.
- The base image is pinned by digest in `sandbox.lock`; tags are never used to select an image.
- The image is rebuilt every Monday, and on any security advisory for a package it contains.
- Egress is denied by default. The allowlist lives next to the image definition, changes only by pull request, is never widened from inside a job, and starts from the October egress logs of the trial jobs.
- Credentials are short-lived tokens minted per job, scoped to the one repository the job works on.
- Job timeout is 45 minutes, with no exceptions (the nightly eval jobs included). A job that hits it fails and is not retried automatically.
- The four shared runners are drained on 2026-11-12 and deleted a week later, once no job references them.

## Consequences

- Reviewers wait about 90 seconds longer for a job to start.
- The team owns the base image build, the weekly rebuild and the allowlist.
- Monthly spend rises by about 40% at today's volume.
- Jobs that relied on a warm cache will be slower or fail; two or three older jobs need their dependencies declared.
