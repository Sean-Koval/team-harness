---
id: monday-image-rebuild-job
type: action
scope: team
status: open
date: '2026-11-05'
owner: dana-example
sources:
- {id: agent-sandbox-decision, resource: team/sources/agent-sandbox-decision.md, hash: "sha256:dfb005bfd5bf729ec1f48e7417fbe16107dc9435f2da05b57364555d7e034595"}
links:
- {type: derived_from, target: agent-sandbox-decision}
- {type: belongs_to, target: PLAT-412}
title: Build the Monday base-image rebuild job
description: A prerequisite before the first sandbox job runs
stale_after: '2026-11-19T00:00:00Z'
author: human:ana-example
---
# dana-example builds the Monday rebuild job

> - Prerequisite: dana-example builds the Monday rebuild job before the first sandbox job runs. Due 2026-11-19.

## Done when

The base image rebuilds every Monday by job, before the first sandbox job runs.
