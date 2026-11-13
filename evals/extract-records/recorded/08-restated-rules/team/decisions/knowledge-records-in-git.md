---
id: knowledge-records-in-git
type: decision
scope: team
status: accepted
date: '2026-11-12'
owner: lead-example
sources:
- {id: records-in-git-decision, resource: team/sources/records-in-git-decision.md, hash: "sha256:4694a83ca8368a9a2ca359d22e65e9a580da29c6b282982bcb5a549f2fc1467d"}
links:
- {type: derived_from, target: records-in-git-decision}
title: Knowledge records live as files in git
description: The wiki is a rendered copy written only by the render job
author: agent:claude-opus-5-5
---
# Knowledge records live as files in git

> Outcome: Decided 2026-11-12 by lead-example. Knowledge records live as files in git; the wiki is rendered from them.

## Decision

- Records are files in git, one file per record, under team/, personal/ or projects/<name>/.
- The wiki is a rendered copy; the render job is its only writer. Never edit it by hand.
- Agents propose records only as a draft PR that a person merges; records change only through a reviewed PR.
