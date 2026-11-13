---
id: add-tools-to-image-not-at-startup
type: convention
scope: team
status: active
date: 2026-11-05
owner: ana-example
sources:
  - {id: agent-sandbox-decision, resource: team/sources/agent-sandbox-decision.md, hash: "sha256:dfb005bfd5bf729ec1f48e7417fbe16107dc9435f2da05b57364555d7e034595"}
links:
  - {type: derived_from, target: agent-sandbox-decision}
  - {type: belongs_to, target: PLAT-412}
  - {type: implements, target: ephemeral-sandbox-per-job}
title: Missing tools go into the base image by PR, never installed at job start-up
description: Keeps the image digest an honest account of what a job ran
author: agent:claude-opus-5-5
---
# Missing tools go into the base image by PR

> "Starting with this decision: a job that needs a tool missing from the base image gets that tool added to the image by pull request." (New convention)

## Rule

A job that needs a tool missing from the base image gets it added to the image by pull request. Jobs never install packages at start-up.

## Why

In the trial, start-up installs were the main invisible source of drift: a job got whatever version the mirror had that day, so the image digest said nothing about what it ran. Adding the tool to the image keeps the digest honest and puts the change in front of a reviewer.

## Examples

A job that needs a CLI not in the image opens a PR to the image definition instead of running `apt-get install` at start-up.
