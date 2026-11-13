---
id: tools-added-to-base-image
type: convention
scope: team
status: active
date: '2026-11-05'
owner: ana-example
sources:
- {id: agent-sandbox-decision, resource: team/sources/agent-sandbox-decision.md, hash: "sha256:dfb005bfd5bf729ec1f48e7417fbe16107dc9435f2da05b57364555d7e034595"}
links:
- {type: derived_from, target: agent-sandbox-decision}
- {type: implements, target: ephemeral-sandbox-per-job}
title: Missing tools go into the base image by PR
description: Jobs never install packages at start-up, so the image digest says what a job ran
author: human:ana-example
---
# Missing tools go into the base image by PR

> Starting with this decision: a job that needs a tool missing from the base image gets that tool added to the image by pull request. Jobs never install packages at start-up.

## Rule

A tool a job needs and the base image lacks is added to the image by pull request. Jobs never install packages at
start-up.

## Why

Start-up installs were the drift nobody could see: the job ran whatever the mirror had that day.
