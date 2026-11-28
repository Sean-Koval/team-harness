---
name: work-start
description: Use at the start of any coding task that has no ticket key yet (a request in chat, a local or cloud session, "just fix this"), and before creating a branch. Finds the existing ticket or files a proposed one, then names the branch with its key.
---

# Starting work

Nothing is edited before the work has a ticket key. If you were given a key, skip to step 3.

Steps 1 and 2 are intake (skipped when you were given a key): delegate them to the `triage` subagent (it runs on
claude-opus-5-5). It finds the ticket or drafts one and says whether it is ready; it files nothing, so you file and
link what it drafts.

1. **Find the ticket.** Search the WORKPROJ project on COMPANY-SITE.atlassian.net with `tracker_search` (`text`, `labels`, `state`), or with the tracker
   server's search (tools: see `jira-ticket`). Look in the project's epic for an open ticket that already covers the
   request: `project = <KEY> AND statusCategory != Done AND text ~ "<words>"` on the tracker server.

   If one matches, use it and say which.
2. **Otherwise file one,** with `tracker_create`, or with the tracker server when it needs the epic or work type
   below. Shape it like the ticket template (`ticket-template.md` in the `jira-ticket` skill):
   - **Work type:** Story (a user-visible change), Task, or Bug.
   - **Parent:** the project's epic, which is its lane: an epic labelled `roadmap`, matched by the repo. Find it with
     `project = <KEY> AND issuetype = Epic AND labels = roadmap` on the tracker server.
   - **Labels:** `proposed`, an execution label and `repo:<repo name>`. The execution label is `exec:pair` when a
     person is working with you, or `exec:human` when only a person can do it. Never `exec:agent`: only a person
     makes work run unattended, and the hook refuses it.
   - **Description:** the goal, acceptance criteria a test can check, the verify command, what is out of scope, and
     the governing ADR or spec.

   During authorized filing, add the exact Jira label `standards-change` when the task calls for establishing, applying, or checking a shared behavior or recurring rule. This includes advice on ownership, a review of whether the rule holds through the real entry point, adoption in a single caller, verification of whether an existing test catches a semantic regression, and checking whether an approval rule applies to the change. Describe the observable promise, a realistic violation, and any valid exception in the acceptance criteria. Routine usage or setup questions, mechanical edits, and reviews without a shared behavior or rule to evaluate use the ordinary labels.

   Tell the ticket's owner the key. Filing a ticket is always allowed. Setting its priority, putting `exec:agent` on it, or
   moving it is not.
3. **Name the branch** `<KEY>-<short-slug>`, for example `SVC-412-retry-queue`. In a cloud session whose branch name
   is assigned for you, keep that branch: the key in the PR title and the `Jira:` line link it instead.
4. **Read the ticket** with `jira-ticket`, and begin. When it needs a design first (an interface, a choice between
   approaches, work across repositories, or a split into several tickets), delegate that to the `designer` subagent
   (it runs on claude-opus-5-5) before writing code.

Some work has no ticket at all: a typo fix, an outside contribution, a dependency bump. It goes on a branch starting
`nokey/`, and its PR carries the `no-ticket` label. That is a deliberate choice, visible in the PR, never a default.
