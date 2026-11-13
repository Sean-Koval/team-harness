---
name: work-docs
description: Use before opening or handing back a pull request, when a change alters behaviour, a convention, an interface or an architecture choice, when implementing a Decision, or when you learned something worth keeping. Says which document goes where (repo, ADR, Confluence) and what the PR's Docs line must say.
---

# Where documentation goes

One owner per fact. Write a fact in its home and link to it from everywhere else. Never copy another tool's status by
hand.

This harness is for personal projects only. Content from an employer (its tickets, pages, code, meeting transcripts, Symphony chat) never comes here: refuse anything tagged `origin: work` or copied from a company system, and never write to a company Atlassian site from this harness.

**Knowledge base for this harness:** the Confluence site `seanmkoval.atlassian.net`, space `SD`. Write pages there and
nowhere else. Never pick a site or space that is not named here, even when the Atlassian server can reach others.

| What | Home | Not here |
| --- | --- | --- |
| Rules an agent must obey: build, test, conventions | The repo's `AGENTS.md`, skills, hooks | Confluence |
| A decision that binds code or architecture | An ADR in the repo's `docs/decisions/`, linked from its Decision ticket | The Jira description |
| A spec for a multi-ticket behaviour change | An OpenSpec change (or `docs/specs/`) in the repo, linked from the epic | Jira beyond a summary |
| A spec for one ticket | The ticket's description, shaped like the ticket template (`jira-ticket` skill) | A separate doc |
| The reasoning behind a decision, at length | Confluence `SD`: Second brain → Decision write-ups, linking its Decision ticket | Chat |
| Notes, how-tos, things learned | Confluence `SD`: Second brain → Notes, one page per subject, linked to its ticket or epic | Chat, Notion |
| Research write-ups | Confluence `SD`: Second brain → Research | Chat |
| A project's goal, milestone, health | The project's epic in Jira (the lane): its Roadmap section and `health:` label | Confluence pages, Notion |
| Ticket status, links, PRs | Jira and GitHub | Any page |

Use the Atlassian MCP server's Confluence tools for pages. Search before you create: update the page that already
covers the subject instead of starting a second one.

## In the same pull request

When the change alters behaviour or a convention, update the repo's docs, `AGENTS.md` or ADR **in the same PR**, not in
a follow-up. When the PR implements a Decision that binds code, add the ADR and put `Decision: <KEY>` in the body.

## The Docs line

Every PR body has a `Docs:` line, and the PR check fails without it. Use one of these forms:

- `Docs: docs/decisions/0007-retry-queue.md` (the files you changed, comma-separated)
- `Docs: <Confluence page URL>` (a page you created or updated)
- `Docs: none needed - <why>` (for example `none needed - internal refactor, no behaviour change`)

`none needed` without a reason is not accepted.
