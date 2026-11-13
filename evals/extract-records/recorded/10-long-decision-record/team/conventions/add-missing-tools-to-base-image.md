---
id: add-missing-tools-to-base-image
type: convention
scope: team
status: active
date: 2026-11-05
owner: ana-example
sources:
  - {id: agent-sandbox-decision, resource: team/sources/agent-sandbox-decision.md, hash: "sha256:dfb005bfd5bf729ec1f48e7417fbe16107dc9435f2da05b57364555d7e034595"}
links:
  - {type: derived_from, target: agent-sandbox-decision}
  - {type: implements, target: agent-jobs-ephemeral-sandboxes}
title: Missing tools go into the base image, never installed at job start-up
description: Keeps the image digest an honest account of what a job ran and puts the change before a reviewer
author: agent:claude-opus-5-5
---
# Missing tools go into the base image, never installed at job start-up

> "Starting with this decision: a job that needs a tool missing from the base image gets that tool added to the image by pull request. Jobs never install packages at start-up." (New convention)

## Rule

A job that needs a tool missing from the base image gets that tool added to the image by pull request. Jobs never install packages at start-up.

## Why

> "In the trial, start-up installs were the main source of drift we could not see. A job that ran `apt-get install` at start-up got whatever version the mirror had that day, so the image digest said nothing about what the job actually ran."

## Examples

- A job needs a CLI the image lacks: open a pull request adding it to the image definition; do not `apt-get install` it in the job.
