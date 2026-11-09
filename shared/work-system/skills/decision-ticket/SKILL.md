---
name: decision-ticket
description: Use whenever you need Sean (or the ticket's owner) to choose something - a missing or contradictory requirement, two reasonable designs, a scope question, anything you would otherwise ask in chat or stop on. Files a Decision ticket in Jira that blocks the work, then stops cleanly.
---

# Decision tickets

A question to a person is a **Decision** work item in the same Jira project, never a chat message, a PR comment or a
silent stop. One question per ticket, so each one can close.

## Filing one

Create an issue with work type **Decision** in the work ticket's project, under the same epic:

| Field | What goes in it |
| --- | --- |
| Summary | The question, ending in `?` |
| Options | Two or three options, each with its consequence in one line |
| Recommendation | The option you recommend and why, in two or three lines |
| Default if unanswered | What happens if nobody answers by Due (usually your recommendation) |
| Scope | Ticket, Project or Suite: how far the answer reaches |
| Due | A date; two working days unless the work is urgent |
| Description | The context: what you found, with links to the code, logs or docs that show it |
| Labels | `decision`, `needs-sean`, `lane:human`, and the work ticket's `repo:` label |

Then:

1. Link it: the Decision **blocks** the work ticket.
2. Comment on the work ticket: `Needs a decision: <DECISION-KEY> <the question>`.
3. Stop. Report the Decision key as your result. Do not keep working on the part the question decides.

Jira automation moves the work ticket to Needs Decision when the blocking link appears, and back when the Decision
is answered; hangar resumes a job when its Decision is answered.

## When it is answered

Sean fills **Chosen** and **Rationale** and moves the Decision to Done (Wont Do when the question is dropped or
replaced). An answered decision is frozen: changing it means a new Decision that supersedes it.

If the answer binds code or architecture, the PR that implements it adds an ADR under the repo's `docs/decisions/`
and says `Decision: <DECISION-KEY>` in its body (`work-docs`).

## What is not a decision

Choices the ticket, the repo's `AGENTS.md`, an ADR or a spec already settles. Read those first; a Decision that
restates one of them wastes Sean's time.
