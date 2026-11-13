---
id: agent-jobs-ephemeral-sandboxes
type: decision
scope: team
status: accepted
date: '2026-11-05'
owner: ana-example
sources:
- id: agent-sandbox-decision
  resource: team/sources/agent-sandbox-decision.md
  hash: sha256:dfb005bfd5bf729ec1f48e7417fbe16107dc9435f2da05b57364555d7e034595
links:
- {type: derived_from, target: agent-sandbox-decision}
- {type: belongs_to, target: PLAT-412}
title: Agent jobs run in ephemeral sandboxes from one pinned base image
description: Ends leaked state, runner drift and long-lived credentials from the shared-runner trial
author: agent:claude-opus-5-5
---
# Agent jobs run in ephemeral sandboxes from one pinned base image

> "Decided 2026-11-05 by ana-example: agent jobs run in one ephemeral sandbox per job, built from a single base image pinned by digest, and the sandbox is destroyed when the job ends. This is option B below." (Outcome, ana-example)

## Decision

Agent jobs (pick up a ticket, work in one repository, open a pull request) run in one fresh sandbox per job, built from a single base image pinned by digest. The sandbox is destroyed when the job ends.

- Nothing survives the job except the pull request, the job trace and the job log.
- The base image is pinned by digest in `sandbox.lock`; tags are never used to select an image.
- The image is rebuilt every Monday, and on any security advisory for a package it contains.
- Egress is denied by default. The allowlist lives next to the image definition, changes only by pull request, and starts from what the trial jobs actually reached (October egress logs).
- Credentials are short-lived tokens minted per job and scoped to the job's one repository.
- Job timeout is 45 minutes, no exceptions (nightly eval jobs included); a job that hits it fails and is not retried automatically.
- The four shared runners are drained on 2026-11-12 and deleted a week later, once no job references them.
- Never widen egress from inside a job.

Scope: agent jobs only. CI checks on agent PRs (existing CI service), the nightly docs build, GPU jobs and local developer runs are not covered.

## Context

Four shared, long-lived runners ran agent jobs since September. State leaked between jobs, runners drifted from hand patching, and credentials stayed on disk for weeks. Job volume is expected to triple by quarter end. Constraints: no job sees another's leftovers; identical start bytes per commit; no credential outlives its job; cold start under two minutes; monthly cost grows by at most half.

## Options considered

- A: keep and harden the shared runners. Rejected: fails isolation and credential constraints by design.
- B: one ephemeral sandbox per job from a pinned image. Chosen: meets all five constraints; about 90 s cold start and about 40% more cost.
- C: vendor hosted runners. Rejected "for now": no digest pinning, per-organization egress, cannot reach the internal mirror, about 70% more cost. Revisit if the vendor ships per-job egress controls and digest pinning.

## Consequences

Reviewers wait about 90 seconds longer per job; the team owns the image build, weekly rebuild and allowlist; spend rises about 40%; two or three older jobs relying on a warm cache will need dependencies declared.
