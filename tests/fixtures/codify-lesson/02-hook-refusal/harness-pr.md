---
title: "ENG-90: codify LES-0011, the guard hook's push refusal says what to do instead"
files:
  - shared/work-system/hooks/guard_work_system.py
lesson: LES-0011
---
Jira: ENG-90
Docs: none (the hook's refusal message only)
Lesson: LES-0011

> The guard hook's refusal of a push to the default branch says what to run instead: push a branch named for the
> ticket and open a pull request as the `github-pr` skill says.

The refusal message for a push to the default branch now names the next step. No records change in this PR; the
lesson is marked codified by a follow-up records PR once this one merges.
