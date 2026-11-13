---
id: rerun-flaky-once-then-report
type: convention
scope: team
status: active
date: '2026-10-20'
owner: ana-example
sources:
- resource: https://wiki.example.invalid/platform/runbooks/flaky-tests
links: []
title: Rerun a flaky test once, then report it
description: Reruns past the first hide real failures
author: human:ana-example
---
# Rerun a flaky test once, then report it

## Rule

A test that fails and then passes on one rerun is reported in the room, not rerun again.
