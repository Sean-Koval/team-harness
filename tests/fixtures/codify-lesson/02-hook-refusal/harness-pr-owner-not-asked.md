---
title: "ENG-90: codify LES-0011, the guard hook's push refusal says what to do instead"
files:
  - shared/work-system/hooks/guard_work_system.py
lesson: LES-0011
draft: true
labels: [needs-owner-review]
review_requested_from: null
---
Jira: ENG-90
Docs: none (the hook's refusal message only)
Lesson: LES-0011
Owner review: the owner must review this before it merges.

> The guard hook's refusal of a push to the default branch says what to run instead: push a branch named for the
> ticket and open a pull request as the `github-pr` skill says.

The refusal message for a push to the default branch now names the next step. No records change in this PR; the
lesson is marked codified by a follow-up records PR once this one merges.

## Follow-up

Once this merges, `team/lessons/LES-0011.md` gets `status: codified` and the link
`{type: codified_as, target: <this PR's merged URL>}`, nothing else changed (drafted in
`.ai-dlc/local/codify-lesson/LES-0011/LES-0011.md`).
