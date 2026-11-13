---
id: records-in-git-wiki-rendered
type: decision
scope: team
status: accepted
date: '2026-11-12'
owner: lead-example
sources:
- {id: records-in-git-decision, resource: team/sources/records-in-git-decision.md, hash: "sha256:4694a83ca8368a9a2ca359d22e65e9a580da29c6b282982bcb5a549f2fc1467d"}
links:
- {type: derived_from, target: records-in-git-decision}
title: Records live in git; the wiki is rendered
description: The render job is the wiki's only writer; agents propose by draft PR
author: human:lead-example
---
# Records live in git; the wiki is rendered

> Outcome: Decided 2026-11-12 by lead-example. Knowledge records live as files in git; the wiki is rendered from them.

## Decision

Records are files in git, one file per record, under the scope folders. The wiki is a rendered copy and the render
job is its only writer, so nobody edits it by hand. Agents propose records only as a draft PR that a person merges.
