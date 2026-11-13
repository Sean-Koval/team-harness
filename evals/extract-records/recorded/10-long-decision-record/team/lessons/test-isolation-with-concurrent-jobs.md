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
  - {type: belongs_to, target: PLAT-412}
title: Verify job isolation with two concurrent jobs before rollout
description: A single green run hid a shared package cache for three weeks
author: agent:claude-opus-5-5
---
# Verify job isolation with two concurrent jobs before rollout

> "Lesson: next time we change how jobs are isolated, run two concurrent jobs against the same repository before rollout and compare what each one can see, instead of trusting a single green run." (What we learned from the shared-runner trial)

## What happened

Two jobs on runner 3 shared the package cache for most of October. One job's integration test passed only because the other had warmed the cache with a newer client library. It was found three weeks late, when the warm job moved runners and the test began failing.

## What to do next time

When changing how jobs are isolated, run two concurrent jobs against the same repository before rollout and compare what each can see.
