---
name: work-start
description: Use at the start of any coding task that has no ticket key yet (a request in chat, a local or cloud session, "just fix this"), and before creating a branch. Finds the existing ticket or files a proposed one, then names the branch with its key.
---

# Starting work

Nothing is edited before the work has a ticket key. If you were given a key, skip to step 3.

1. **Find the ticket.** Search the WORKPROJ project on COMPANY-SITE.atlassian.net with JQL through the Atlassian MCP server. Look in the project's epic for
   an open ticket that already covers the request:

   `project = <KEY> AND statusCategory != Done AND text ~ "<words>"`

   If one matches, use it and say which.
2. **Otherwise file one.** Shape it like the ticket template (`ticket-template.md` in the
   `jira-ticket` skill):
   - **Work type:** Story (a user-visible change), Task, or Bug.
   - **Parent:** the project's epic, which is its lane. Find it with
     `project = <KEY> AND issuetype = Epic AND labels = roadmap`, matched by the repo.
   - **Labels:** `proposed`, an execution label and `repo:<repo name>`. The execution label is `exec:pair` when a
     person is working with you, or `exec:human` when only a person can do it. Never `exec:agent`: only a person
     makes work run unattended, and the hook refuses it.
   - **Description:** the goal, acceptance criteria a test can check, the verify command, what is out of scope, and
     the governing ADR or spec.

   Tell the ticket's owner the key. Filing a ticket is always allowed. Setting its priority, putting `exec:agent` on it, or
   moving it is not.
3. **Name the branch** `<KEY>-<short-slug>`, for example `SVC-412-retry-queue`. In a cloud session whose branch name
   is assigned for you, keep that branch: the key in the PR title and the `Jira:` line link it instead.
4. **Read the ticket** with `jira-ticket`, and begin.

Some work has no ticket at all: a typo fix, an outside contribution, a dependency bump. It goes on a branch starting
`nokey/`, and its PR carries the `no-ticket` label. That is a deliberate choice, visible in the PR, never a default.
