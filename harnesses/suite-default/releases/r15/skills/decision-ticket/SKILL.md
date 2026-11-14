---
name: decision-ticket
description: Use whenever you need Sean to choose something (a missing or contradictory requirement, two reasonable designs, a scope question, anything you would otherwise ask in chat or stop on), and when Sean rules on an open Decision in chat or a comment ("go with option 1"). Files a Decision that blocks the work and stops; after a ruling, drafts Chosen and Rationale and lists the tickets to move for confirmation.
---

# Decision tickets

A question to a person is a Decision in the same Jira project. It is never a chat message, a PR comment or a silent
stop. Ask one question per ticket, so each one can close.

## Filing one

Use the tools `jira-ticket` names. A Decision needs its work type, fields and a link, which ai-dlc's
`tracker_create` doesn't set yet: file it on the tracker server, and comment with `tracker_comment` or that server.

Create an issue with work type **Decision** in the work ticket's project, under the same epic, and fill its fields:

| Field | What goes in it |
| --- | --- |
| Summary | The question, ending in `?` |
| Options | Two or three options, each with its consequence in one line |
| Recommendation | The option you recommend and why, in two or three lines |
| Default if unanswered | What happens if nobody answers by Due (usually your recommendation) |
| Due | A date: two working days, unless the work is urgent |
| Chosen | Empty until it is ruled on |
| Rationale | Empty until it is ruled on |
| Description | The context: what you found, with links to the code, logs or docs that show it |
| Labels | `decision`, `human-decision` (the label Sean's decisions view filters on), `exec:human`, the work ticket's `repo:` label, and `needs-sean` until the label cleanup (KAN-326) retires it; assign it to Sean |

Then:

1. **Link it.** The Decision **blocks** the work ticket. Every Decision blocks at least one ticket.
2. **Comment on the work ticket:** `Needs a decision: <DECISION-KEY> <the question>`.
3. **Stop.** Report the Decision key as your result. Do not keep working on the part the question decides.

## When Sean rules

A ruling often arrives as a line in chat or a comment ("go with option 1"). Turn it into a record. Never act on it
directly.

1. **Draft the outcome on the Decision.** Write the ruled option into **Chosen**. In **Rationale**, put the reason in
   one to three lines, quoting or linking the ruling. If you write a reason you inferred, mark it as inferred.
2. **List the follow-through.** Read the tickets the Decision blocks, and any ticket the ruling names. Comment on the
   Decision with what you would do:

   ```
   Ruling recorded: Chosen = <option>. To apply it:
   - ABC-12: To Do -> In Progress (unblocked by this ruling)
   - ABC-15: To Do -> Wont Do (superseded by option 1)
   Confirm or correct this list, then make the moves: I don't transition tickets.
   ```
3. **Wait for confirmation.** Sean confirms or corrects the list, then moves the tickets and closes the Decision
   (Done; Wont Do when the question is dropped or replaced). You never call a transition: the hook refuses it, and a
   ruling is not a confirmation.

An answered Decision is frozen. Changing it means filing a new Decision that supersedes it.

If the answer binds code or architecture, the PR that implements it adds an ADR under the repo's `docs/decisions/`, and
its body says `Decision: <DECISION-KEY>` (`work-docs`).

## What is not a decision

Some choices are already settled by the ticket, the repo's `AGENTS.md`, an ADR or a spec. Read those first. A
Decision that restates one of them wastes Sean's time.
