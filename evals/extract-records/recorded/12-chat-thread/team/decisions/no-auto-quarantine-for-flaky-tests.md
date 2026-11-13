---
id: no-auto-quarantine-for-flaky-tests
type: decision
scope: team
status: accepted
date: '2026-11-11'
owner: ana-example
sources:
- id: token-refresh-flake-thread
  resource: team/sources/token-refresh-flake-thread.md
  hash: sha256:767c6d5dd93cffb870ff9cf3007be5f5cd40ca516416cf4b17f6fefc561bc674
links:
- {type: derived_from, target: token-refresh-flake-thread}
title: Flaky tests are not auto-quarantined after a second failure
description: Quarantine would have hidden the sandbox clock skew and lets agent PRs go green when they should not
author: agent:claude-opus-5-5
---
# Flaky tests are not auto-quarantined after a second failure

> "thanks. not adopting the quarantine rule then" ([09:30] Ana Reyes)

## Decision

The proposed rule to quarantine every flaky test with a `@flaky` marker within an hour of its second failure was withdrawn and not adopted, including the variant where quarantine needs a ticket ([09:30] Chidi Obi: "withdrawn, we keep rerun once then report"). The existing rerun-once-then-report rule (rerun-flaky-once-then-report) is unchanged.

## Context

- This test would have been quarantined two weeks earlier and the clock skew never found (Ana, Dana).
- A quarantined test in an agent job makes the agent's PR go green when it should not; reviewers trust green (Ben).
- A ticketed quarantine list would end up unread (Ana).
- Proposed by Chidi to cut rerun cost; reruns were in fact once per failure.
