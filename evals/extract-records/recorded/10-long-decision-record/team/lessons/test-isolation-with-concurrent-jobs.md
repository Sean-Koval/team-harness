---
id: test-isolation-with-concurrent-jobs
type: lesson
scope: team
status: open
date: 2026-11-05
owner: ana-example
sources:
  - {id: agent-sandbox-decision, resource: team/sources/agent-sandbox-decision.md, hash: "sha256:dfb005bfd5bf729ec1f48e7417fbe16107dc9435f2da05b57364555d7e034595"}
links:
  - {type: derived_from, target: agent-sandbox-decision}
title: Prove job isolation with two concurrent jobs before rollout
description: A single green run hid a shared package cache for three weeks
author: agent:claude-opus-5-5
---
# Prove job isolation with two concurrent jobs before rollout

> "Lesson: next time we change how jobs are isolated, run two concurrent jobs against the same repository before rollout and compare what each one can see, instead of trusting a single green run." (What we learned from the shared-runner trial)

## What happened

> "Two jobs on runner 3 shared the package cache for most of October. One job's integration test passed only because the other job had warmed the cache with a newer client library. We found it three weeks late, when the warm job was moved to another runner and the test began failing for no visible reason."

## What to do next time

When changing how jobs are isolated, run two concurrent jobs against the same repository before rollout and compare what each one can see, instead of trusting a single green run.
