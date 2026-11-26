---
name: release-approvals
description: Use as soon as a work PR is open (or hangar has opened it), when asked to "get it reviewed", "request approval", "file the approval tickets", or "post in the review room". Runs the approval gates the company's org overlay declares (one ticket per gate that applies, filed after the PR is open), records each gate's line in the PR, and drafts (never posts) the review request.
---

# Release approvals (the gates the org declares)

A work PR is approved by people outside the team, each from a ticket of their own. Which tickets, in which projects,
and when each one applies is the company's flow: its org overlay declares it, and the tables below are rendered from
it. You prepare the tickets. You approve nothing, merge nothing and post nothing.

Employer content (tickets, pages, code, logs, meeting transcripts, Symphony chat) stays on the company's systems and in tools the company approved on the work machine. Never write it to any other Atlassian site, to Notion, to a personal notes vault, or to any personal sync or backup, and never tag it for a personal system. If the knowledge-base site or space this harness names still reads COMPANY-SITE or COMPANY-SPACE, the company overlay was not applied: write no page, and say so in the PR.

**The org overlay is not applied.** This harness carries the public placeholder (`orgs/example-co`, `placeholder: true`): its projects and room are not real. File no ticket and add no gate line. Say in the PR and on the work ticket that the company's org overlay is not applied, and list the gates below that would apply. Still draft the review request.

## First, read `org-process`

`org-process` is the company's own description of its flow. Read it before you file anything. If it and the tables
below disagree, `org-process` wins: follow it, and say in the PR which row differed.

## Ticket types

| Ticket type | Project | Issue type | Role | Summary |
| --- | --- | --- | --- | --- |
| `work` | `WORKPROJ` | Story | work | - |
| `infosec-review` | `SECPROJ` | Task | approval | `Infosec review: {repo}` |
| `ess-request` | `ESSPROJ` | Task | approval | `ESS request: {pr_title}` |
| `arch-review` | `ARCHPROJ` | Task | approval | `Architecture review: {pr_title}` |
| `change-request` | `CHGPROJ` | Change | approval | `Release: {pr_title}` |

## Gates, in order

Review teams: SRE (`sre`, GitHub team `@COMPANY-ORG/sre`); Infosec (`infosec`); ESS (`ess`); Architecture board (`architecture-board`).

Stages, in order: dev (merges into `main`); prod (a later step: the PR check does not hold the merge for it).

| Gate | Stage | Approved on | Approvers | Applies when | Links | Filed by | PR line | Approved when |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `sre` | dev | the work ticket | SRE | always | pr | - | - | status SRE Approved and an approving GitHub review of the PR's latest commit from a member of `@COMPANY-ORG/sre` |
| `infosec` | dev | `infosec-review` in `SECPROJ`, one per repository (reuse an open one) | Infosec | always | repo | agent | `Infosec: <KEY>` | status Approved |
| `ess` | dev | `ess-request` in `ESSPROJ` | ESS | the work ticket is a `Change Request` | pr, work | person | `ESS: <KEY>` | field `customfield_10050` is Approved |
| `architecture` | dev | `arch-review` in `ARCHPROJ` | Architecture board | the PR or work ticket has label `architecture` | pr, work | agent | `Architecture: <KEY>` | nothing waits on it (filed for the record) |
| `release` | prod | `change-request` in `CHGPROJ` | SRE | always | work | person | `Release: <KEY>` | status Approved |

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

Room: the team's review room. Template:

````text
Review please: {pr_url}
{work_key}: {summary}
{gate_lines}
Risk: {risk}
````

You have no chat tool, and you never use one for this. Write the message into your hand-back (or the PR description,
under **Review request**) for a person to post. `{summary}` is one line on what changes and why; `{gate_lines}` is
one `<PR line>: <KEY>` line per gate that applies; `{risk}` is low, medium or high, and why in a few words.

## Afterwards

Approval can take from minutes to hours. Do not chase it, re-file it, move any ticket, approve or merge. The
approvals, and the merge a person makes after them, move the work ticket.
