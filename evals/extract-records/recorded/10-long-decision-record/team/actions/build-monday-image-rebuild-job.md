---
id: build-monday-image-rebuild-job
type: action
scope: team
status: open
date: '2026-11-05'
owner: dana-example
stale_after: '2026-11-19'
sources:
- id: agent-sandbox-decision
  resource: team/sources/agent-sandbox-decision.md
  hash: sha256:dfb005bfd5bf729ec1f48e7417fbe16107dc9435f2da05b57364555d7e034595
links:
- {type: derived_from, target: agent-sandbox-decision}
- {type: belongs_to, target: PLAT-412}
title: Build the Monday base-image rebuild job
description: Prerequisite that must exist before the first sandbox job runs
author: agent:claude-opus-5-5
---
# Build the Monday base-image rebuild job

> "Prerequisite: dana-example builds the Monday rebuild job before the first sandbox job runs. Due 2026-11-19." (Follow-ups)

## Action

dana-example builds the job that rebuilds the base image every Monday (and on security advisories), before the first sandbox job runs. Due 2026-11-19.
