---
id: ephemeral-sandbox-per-job
type: decision
scope: team
status: accepted
date: 2026-11-05
owner: ana-example
sources:
  - {id: agent-sandbox-decision, resource: team/sources/agent-sandbox-decision.md, hash: "sha256:dfb005bfd5bf729ec1f48e7417fbe16107dc9435f2da05b57364555d7e034595"}
links:
  - {type: derived_from, target: agent-sandbox-decision}
  - {type: belongs_to, target: PLAT-412}
title: Agent jobs run in ephemeral sandboxes from one pinned base image
description: Ends state leaks, runner drift and long-lived credentials from the shared-runner trial
valid_from: 2026-11-05
author: agent:claude-opus-5-5
---
# Agent jobs run in ephemeral sandboxes from one pinned base image

> "Decided 2026-11-05 by ana-example: agent jobs run in one ephemeral sandbox per job, built from a single base image pinned by digest, and the sandbox is destroyed when the job ends." (Outcome, ana-example)

## Context

Since September agent jobs ran on four shared, long-lived runners, a trial and never a decision. State leaked between jobs, runners drifted, and credentials stayed on disk for weeks. Job volume is expected to triple by the end of the quarter. Constraints: no job sees another's leftovers; identical bytes for two runs of one commit; no credential outlives its job; cold start under two minutes; cost growth at most half.

Scope: agent jobs only (pick up a ticket, work in one repository, open a pull request). Not CI checks on those PRs, not the nightly docs build, not GPU jobs, not local runs.

## Options considered

- A: keep and harden the shared runners. Fails isolation and credential constraints by design.
- B: one ephemeral sandbox per job from a pinned base image (chosen). About 90 s cold start, about 40% more cost.
- C: vendor-hosted runners. Image cannot be pinned by digest, per-organization egress only, about 70% more cost. Dropped for now; may be revisited if the vendor ships per-job egress controls and digest pinning.

## Decision

- Each job gets a fresh sandbox. Nothing survives the job except the pull request, the job trace and the job log.
- The base image is pinned by digest in `sandbox.lock`. Tags are never used to select an image.
- The image is rebuilt every Monday, and also on any security advisory for a package it contains.
- Egress is denied by default. The allowlist lives next to the image definition and changes only by pull request; it starts from what the trial jobs reached (October egress logs).
- Credentials are short-lived tokens minted per job and scoped to the one repository the job works on.
- The job timeout is 45 minutes, with no exceptions (nightly eval jobs included). A job that hits it fails and is not retried automatically.
- The four shared runners are drained on 2026-11-12 and deleted a week later, once no job references them.

## Consequences

- Reviewers wait about 90 seconds longer for a job to start.
- The team owns the base image build, the weekly rebuild and the allowlist.
- Monthly spend rises by about 40% at today's volume.
- Jobs that relied on a warm cache will be slower or fail; two or three older jobs need their dependencies declared.
