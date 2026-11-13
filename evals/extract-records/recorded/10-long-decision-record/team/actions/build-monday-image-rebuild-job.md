---
id: build-monday-image-rebuild-job
type: action
scope: team
status: open
date: 2026-11-05
owner: dana-example
sources:
  - {id: agent-sandbox-decision, resource: team/sources/agent-sandbox-decision.md, hash: "sha256:dfb005bfd5bf729ec1f48e7417fbe16107dc9435f2da05b57364555d7e034595"}
links:
  - {type: derived_from, target: agent-sandbox-decision}
title: Build the Monday base-image rebuild job
description: Prerequisite that must exist before the first sandbox job runs
stale_after: 2026-11-19T00:00:00Z
author: agent:claude-opus-5-5
---
# Who owes what

> "Prerequisite: dana-example builds the Monday rebuild job before the first sandbox job runs. Due 2026-11-19." (Follow-ups)

dana-example owes the scheduled job that rebuilds the base image every Monday (and on security advisories), for decision agent-jobs-ephemeral-sandboxes.

## Done when

The Monday rebuild job exists and runs before the first sandbox job runs, by 2026-11-19.
