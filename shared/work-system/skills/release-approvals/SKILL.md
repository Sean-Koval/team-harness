---
name: release-approvals
description: Use as soon as a work PR is open (or hangar has opened it), when asked to "get it reviewed", "request approval", "file the approval tickets", or "post in the review room". Runs the approval gates the company's org overlay declares (one ticket per gate that applies, filed after the PR is open), records each gate's line in the PR, and drafts (never posts) the review request.
---

# Release approvals (the gates the org declares)

A work PR is approved by people outside the team, each from a ticket of their own. Which tickets, in which projects,
and when each one applies is the company's flow: its org overlay declares it, and the tables below are rendered from
it. You prepare the tickets. You approve nothing, merge nothing and post nothing.

{{wall}}

{{org_status}}

## First, read `org-process`

`org-process` is the company's own description of its flow. Read it before you file anything. If it and the tables
below disagree, `org-process` wins: follow it, and say in the PR which row differed.

## Ticket types

{{org_ticket_types}}

## Gates, in order

{{org_gates}}

Run each gate after the PR is open, in the order above:

1. **Does it apply?** A gate with a stage applies only at that stage. A stage that merges into a branch is this PR's
   when the PR targets that branch; a later stage (no branch) is run by people at release, so list its gates in the
   hand-back and do nothing for them now. Then `always` applies to every PR. A path rule applies when a path the PR
   changes matches one of its globs; a label rule when the PR or the work ticket has one of its labels; an issue type
   or project rule when the work ticket is of that type or in that project. If none matches, say so in the hand-back.
2. **Approved on the work ticket?** File nothing and add no line. If its Links column names `pr`, add the PR to the
   work ticket as a remote link (or its URL in the description): the PR check looks there, not in comments. Comment
   that it waits on the Approvers. If the gate names a GitHub review, say in the hand-back which team must approve
   the PR on GitHub; a person requests it.
3. **File it, or ask for it.** Filed by `agent`: on the tracker server (another project and a work type, which
   ai-dlc's `tracker_create` doesn't set; tools: see `jira-ticket`), create one ticket of the gate's type, in its
   project, with its issue type and summary (fill `{work_key}`, `{pr_title}`, `{repo}` and `{pr_url}`). Its
   description gives the PR URL, what changes, the rollout and rollback, and what a reviewer should look at first.
   Link what the Links column names: `pr` as a remote link (or its URL in the description), `work` as `relates to`
   the work ticket, `repo` as the repository URL. Filed by `person`: file nothing; ask for that ticket in the PR,
   and leave its line to them. One per repository: search the project for an open ticket for this repository first
   and reuse its key; file one only when none is open.
4. **Record it.** Add the gate's PR line to the PR body (for example `Infosec: <KEY>`), and comment on the work
   ticket: `<PR line>: <KEY> for <PR URL>`. The PR check requires the line of every gate that applies at this
   stage before a merge. A gate whose ticket nothing waits on still needs its line.

One ticket per gate per PR, unless the gate is one per repository. If one already exists (search its project by the
summary), reuse its key instead of filing again. If a project or issue type doesn't exist, or you may not create in
it, file nothing for that gate: say which value is missing, in the PR and on the work ticket.

## Review request: drafted, never posted

{{org_review_request}}

You have no chat tool, and you never use one for this. Write the message into your hand-back (or the PR description,
under **Review request**) for a person to post. `{summary}` is one line on what changes and why; `{gate_lines}` is
one `<PR line>: <KEY>` line per gate that applies; `{risk}` is low, medium or high, and why in a few words.

## Afterwards

Approval can take from minutes to hours. Do not chase it, re-file it, move any ticket, approve or merge. The
approvals, and the merge a person makes after them, move the work ticket.
