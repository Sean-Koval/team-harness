---
id: agent-sandbox-decision
type: source
scope: team
status: raw
date: '2026-11-05'
owner: ana-example
sources:
- resource: https://wiki.example.invalid/platform/decisions/agent-sandboxes
  hash: sha256:dfb005bfd5bf729ec1f48e7417fbe16107dc9435f2da05b57364555d7e034595
links: []
description: 'Decision: agent jobs run in ephemeral sandboxes from one pinned base image'
schema_version: 1
revision: '1'
provider: wiki
title: 'Decision: agent jobs run in ephemeral sandboxes from one pinned base image'
observed_at: '2026-11-05T16:00:00+00:00'
obligations: []
---
# Decision: agent jobs run in ephemeral sandboxes from one pinned base image

| | |
| --- | --- |
| Status | Decided |
| Decision owner | ana-example |
| Decided | 2026-11-05 |
| Reviewers | ben-example, chidi-example, dana-example |
| Ticket | PLAT-412 |
| Supersedes | nothing (the shared runners were a trial, never a decision) |

## Outcome

Decided 2026-11-05 by ana-example: agent jobs run in one ephemeral sandbox per job, built from a single base image pinned by digest, and the sandbox is destroyed when the job ends. This is option B below.

## Context

Since September the team has run agent jobs on four shared, long-lived runners. The trial was meant to last two weeks and lasted eight. It worked well enough that nobody stopped it, and badly enough that most of the incidents in October trace back to it.

Three problems kept coming up. First, state leaked between jobs. Runners kept their package cache, their temporary directories and, in one case, a checked-out branch from an earlier job. Second, the runners drifted. Each one had been patched by hand at different times, so the same job could pass on runner 2 and fail on runner 4. Third, credentials lived on the runners for weeks. A token minted for one repository sat on disk long after the job that needed it had finished.

We also expect job volume to triple by the end of the quarter, when the second team starts filing agent tickets. Shared runners would need to grow from four to roughly twelve, and every one of them would drift on its own schedule.

The constraints we set before looking at options:

- A job must not see anything another job left behind.
- Two runs of the same job on the same commit must start from identical bytes.
- No credential may outlive the job it was minted for.
- Cold start must stay under two minutes, or reviewers stop waiting for agent PRs and the queue backs up.
- The monthly cost may grow, but by no more than half.

## Scope

This covers agent jobs only: the jobs that pick up a ticket, work in one repository and open a pull request. It does not cover the CI checks that run on those pull requests, which stay on the existing CI service, or the nightly docs build. GPU jobs are out of scope; none exist yet, and when the first one does it will need its own image and probably its own decision. Local runs on a developer's machine are unaffected.

## Options considered

### Option A: keep the shared runners, and harden them

Wipe caches and temporary directories between jobs, rebuild each runner from a script every Sunday, and rotate credentials nightly.

- For: no migration; jobs start in seconds because the runner is already warm.
- Against: wiping is a list we would have to keep complete, and we already missed the branch checkout once. Drift returns between Sunday rebuilds. Nightly rotation still leaves a token on disk for up to a day.
- Cost: lowest. About the same as today.

### Option B: one ephemeral sandbox per job, built from a pinned base image

Each job gets a fresh sandbox created from one base image, referenced by digest. The sandbox is destroyed when the job ends. Credentials are minted for the job and expire with it.

- For: isolation is structural rather than a cleanup list. Every job starts from the same bytes. Credentials cannot outlive the job.
- Against: cold start rises to about 90 seconds. Anything a job needs must be in the image or fetched through the egress allowlist. We must own an image build.
- Cost: about 40% more than today at current volume, mostly sandbox start-up time.

### Option C: hosted runners from the CI vendor

Use the vendor's per-job hosted runners and their images.

- For: no image to own; the vendor handles patching.
- Against: we cannot pin their image by digest, only by a moving label, so two runs of the same commit may differ. Their egress controls are per organization, not per job. Their runners cannot reach the internal package mirror without a network change that infosec has already declined once.
- Cost: about 70% more than today, over our limit.

## Recommendation

The review draft recommended option B. It is the only option that meets all five constraints. Option A fails the first and third constraints by design, since cleanup lists and rotation windows leave gaps. Option C fails the second, and its cost is over the limit. We recommended B, with the image rebuilt weekly so that pinning does not turn into running stale packages.

## Decision details

- Each job gets a fresh sandbox. Nothing survives the job except the pull request, the job trace and the job log.
- The base image is pinned by digest in `sandbox.lock`. Tags are never used to select an image.
- The image is rebuilt every Monday, and also on any security advisory for a package it contains.
- Egress is denied by default. The allowlist lives next to the image definition and changes only by pull request.
- Credentials are short-lived tokens minted per job and scoped to the one repository the job works on.
- The job timeout is 45 minutes. A job that hits it fails and is not retried automatically.
- The four shared runners are drained on 2026-11-12 and deleted a week later, once no job references them.

## New convention

Starting with this decision: a job that needs a tool missing from the base image gets that tool added to the image by pull request. Jobs never install packages at start-up.

Why: in the trial, start-up installs were the main source of drift we could not see. A job that ran `apt-get install` at start-up got whatever version the mirror had that day, so the image digest said nothing about what the job actually ran. Adding the tool to the image keeps the digest honest and puts the change in front of a reviewer.

## Unchanged from earlier decisions

These still hold and are listed here so this page reads on its own. Nothing in this decision changes them.

- Agents open draft pull requests only; a person reviews and merges.
- Every job branch starts with its ticket key.
- Job traces are kept for 14 days.
- Agents never merge at work, whatever the checks say.

## Rules (restated for the runbook)

The runbook copies this list verbatim, so it is repeated here.

- Never reuse a sandbox between jobs.
- Never select the base image by tag.
- Never install packages at job start-up.
- Never widen egress from inside a job.
- Draft pull requests only.

## What we learned from the shared-runner trial

Two jobs on runner 3 shared the package cache for most of October. One job's integration test passed only because the other job had warmed the cache with a newer client library. We found it three weeks late, when the warm job was moved to another runner and the test began failing for no visible reason.

Lesson: next time we change how jobs are isolated, run two concurrent jobs against the same repository before rollout and compare what each one can see, instead of trusting a single green run.

## Consequences

- Reviewers wait about 90 seconds longer for a job to start. We judged that acceptable; the queue today is minutes, not seconds.
- The team owns the base image build, the weekly rebuild and the allowlist.
- Monthly spend rises by about 40% at today's volume. Finance has the estimate.
- A job that relied on a warm cache will be slower or will fail. We expect two or three of the older jobs to need their dependencies declared properly.

## Follow-ups

- Prerequisite: dana-example builds the Monday rebuild job before the first sandbox job runs. Due 2026-11-19.
- Not planned now: a dashboard showing each image's age. It would be nice to have; we may look again in the first quarter.

## Review comments

**ben-example (2026-11-04):** Does the 45-minute timeout apply to the nightly eval jobs too? Some of those ran long on the shared runners.

> **ana-example:** Yes, no exceptions. The eval jobs fit in 30 minutes once they stop reinstalling their dependencies.

**chidi-example (2026-11-04):** Are we dropping option C for good?

> **ana-example:** For now. We can look again if the vendor ships per-job egress controls and digest pinning.

**dana-example (2026-11-05):** The allowlist should start from what the trial jobs actually reached, not from a guess. The draft allowlist in the image repository already comes from the October egress logs.

> **ana-example:** Good, that is what I hoped. Approving.
