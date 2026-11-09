---
name: release-approvals
description: Use as soon as a work PR is open (or hangar has opened it), when asked to "get it reviewed", "request SRE approval", "file the infosec ticket", or "post in the review room". Files the SRE approval ticket that links the PR and the infosec ticket that links the repository, and drafts (never posts) the review request for the team's Symphony room.
---

# Release approvals (company SDLC)

A work PR is approved by people outside the team. SRE reviews a Jira ticket that links the PR, then approves or merges
the PR. Infosec reviews the code from its own ticket. The team asks for review in its Symphony room.

You prepare all three. You approve nothing, merge nothing and post nothing.

{{wall}}

The projects, the issue types and the room name come from the repository's `AGENTS.md`, or from the team's
Engineering page in `{{kb_space}}`. If either one does not name them, file nothing: say which value is missing, in the
PR and on the work ticket.

## 1. SRE approval ticket

File one per PR, in the SRE project:

| Field | What goes in it |
| --- | --- |
| Summary | `SRE approval: <WORK-KEY> <PR title>` |
| Description | The PR URL, what changes in production, the rollout and rollback, and who to ask |
| Links | `relates to` the work ticket, and the PR as a remote link (or its URL in the description) |

Then comment on the work ticket: `SRE approval: <SRE-KEY> for <PR URL>`.

## 2. Infosec review ticket

File it in the infosec project, separately from the SRE ticket:

| Field | What goes in it |
| --- | --- |
| Summary | `Infosec review: <repo> <WORK-KEY>` |
| Description | The repository URL and the PR URL, what the change touches (auth, data handling, dependencies, network, secrets), and anything you want a reviewer to look at first |
| Links | `relates to` the work ticket |

Then comment on the work ticket: `Infosec review: <INFOSEC-KEY>`.

## 3. Review request for the Symphony room: drafted, never posted

You have no chat tool, and you never use one for this. Write the message into your hand-back (or the PR's
description, under **Review request**) for a person to post:

```
Review please: <PR URL>
<WORK-KEY>: <one line on what changes and why>
SRE ticket: <SRE-KEY> · Infosec: <INFOSEC-KEY>
Risk: <low / medium / high, and why in a few words>
```

## Afterwards

Approval can take from minutes to hours. Do not chase it, re-file it, or move any ticket. The SRE approval, and the
merge that follows it, move the work ticket.
