---
name: work-docs
description: Use before opening or handing back a pull request, when a change alters behaviour, a convention, an interface or an architecture choice, when implementing a Decision, or when you learned something worth keeping. Says which document goes where (repo, ADR, Confluence) and what the PR's Docs line must say.
---

# Where documentation goes

One owner per fact. Write a fact in its home and link to it from everywhere else. Never copy another tool's status by
hand.

{{wall}}

**Knowledge base for this harness:** the Confluence site `{{kb_site}}`, space `{{kb_space}}`. A session does not
write pages: it proposes knowledge records (skill `extract-records`, `ai-dlc knowledge records propose`), and the
render job publishes them to that space once their PR merges. The session hook refuses page writes, unless the
profile's `wiki_write_allow` names the site and space. Never pick a site or space that is not named here.

| What | Home | Not here |
| --- | --- | --- |
| Rules an agent must obey: build, test, conventions | The repo's `AGENTS.md`, skills, hooks | Confluence |
| A decision that binds code or architecture | An ADR in the repo's `docs/decisions/`, linked from its Decision ticket | The Jira description |
| A spec for a multi-ticket behaviour change | An OpenSpec change (or `docs/specs/`) in the repo, linked from the epic | Jira beyond a summary |
| A spec for one ticket | The ticket's description, shaped like the ticket template (`jira-ticket` skill) | A separate doc |
| The reasoning behind a decision, at length | Confluence `{{kb_space}}`: {{kb_decisions}}, linking its Decision ticket | Chat |
| Notes, how-tos, things learned | Confluence `{{kb_space}}`: {{kb_notes}}, one page per subject, linked to its ticket or epic | Chat, Notion |
| Research write-ups | Confluence `{{kb_space}}`: {{kb_research}} | Chat |
| A project's goal, milestone, health | The project's epic in Jira (the lane): its Roadmap section and `health:` label | Confluence pages, Notion |
| Ticket status, links, PRs | Jira and GitHub | Any page |

Read pages with the wiki server's read tools. Search before you propose: amend the record that already covers the
subject instead of starting a second one. The Confluence rows above are where the render job publishes.

## In the same pull request

When the change alters behaviour or a convention, update the repo's docs, `AGENTS.md` or ADR **in the same PR**, not in
a follow-up. When the PR implements a Decision that binds code, add the ADR and put `Decision: <KEY>` in the body.

## The Docs line

Every PR body has a `Docs:` line, and the PR check fails without it. Use one of these forms:

- `Docs: docs/decisions/0007-retry-queue.md` (the files you changed, comma-separated)
- `Docs: <records PR or page URL>` (the knowledge records you proposed, or the page the render job published)
- `Docs: none needed - <why>` (for example `none needed - internal refactor, no behaviour change`)

`none needed` without a reason is not accepted.
