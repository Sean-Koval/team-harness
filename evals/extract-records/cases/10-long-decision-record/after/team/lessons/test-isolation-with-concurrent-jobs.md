---
id: test-isolation-with-concurrent-jobs
type: lesson
scope: team
status: open
date: '2026-11-05'
owner: ana-example
sources:
- {id: agent-sandbox-decision, resource: team/sources/agent-sandbox-decision.md, hash: "sha256:dfb005bfd5bf729ec1f48e7417fbe16107dc9435f2da05b57364555d7e034595"}
links:
- {type: derived_from, target: agent-sandbox-decision}
title: Test an isolation change with two concurrent jobs
description: A shared cache made one job's test pass for three weeks before anyone noticed
author: human:ana-example
---
# Test an isolation change with two concurrent jobs

> Lesson: next time we change how jobs are isolated, run two concurrent jobs against the same repository before rollout and compare what each one can see, instead of trusting a single green run.

## What happened

Two jobs on one shared runner shared the package cache for most of October. One job's test passed only because the
other had warmed the cache; it was found three weeks late.

## What to do next time

Before rolling out an isolation change, run two concurrent jobs against the same repository and compare what each
one can see.
