---
id: render-job-service-account
type: action
scope: team
status: open
date: '2026-11-12'
owner: unknown
sources:
- {id: records-in-git-decision, resource: team/sources/records-in-git-decision.md, hash: "sha256:4694a83ca8368a9a2ca359d22e65e9a580da29c6b282982bcb5a549f2fc1467d"}
links:
- {type: derived_from, target: records-in-git-decision}
title: Give the render job its own service account
description: A prerequisite for go-live of the rendered wiki
tags: [owner-unknown]
author: human:lead-example
---
# Someone sets up the render job's service account

> - Prerequisite: the render job needs its own service account before go-live.

## Done when

The render job runs under its own service account.
