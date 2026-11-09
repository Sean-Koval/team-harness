---
name: work-start
description: Use at the start of any coding task that has no ticket key yet (a request in chat, a local or cloud session, "just fix this"), and before creating a branch. Finds the existing ticket or files a proposed one, then names the branch with its key.
---

# Starting work

Nothing is edited before the work has a ticket key. If you were given a key, skip to step 3.

1. **Find the ticket.** Search Jira (JQL through the Atlassian MCP server) in the project's epic for an open ticket
   that already covers the request: `project = <KEY> AND statusCategory != Done AND text ~ "<words>"`. If one
   matches, use it and say which.
2. **Otherwise file one.** Work type Story (a user-visible change), Task, or Bug; under the project's roadmap epic
   (`project = <KEY> AND issuetype = Epic AND labels = roadmap`, matched by the repo); labels `proposed`, a lane and
   `repo:<repo name>`. The lane is `lane:pair` when Sean is working with you, or `lane:human` when only he can do
   it; never `lane:agent`, because only Sean makes work run unattended (the hook refuses it). The
   description holds the goal, acceptance criteria a test can check, the verify command, and what is out of scope.
   Tell Sean the key. Filing a ticket is always allowed; setting priority, `lane:agent` or moving it is not.
3. **Name the branch** `<KEY>-<short-slug>` (`KAN-412-retry-queue`). In a cloud session whose branch name is
   assigned for you, keep that branch: the key in the PR title and the `Jira:` line link it instead.
4. Read the ticket with `jira-ticket` and begin.

Work with no ticket at all (a typo fix, an outside contribution, a dependency bump) goes on a branch starting
`nokey/` and its PR carries the `no-ticket` label. That is a deliberate choice, visible in the PR, never a default.
