# Jira and Confluence organization

How docs and tickets stay organized across Jira and Confluence, and which skills, hooks and Jira tools keep them
that way. The status, label and field model itself is in
[cabinet `config/work-system/`](https://github.com/Sean-Koval/cabinet/tree/main/config/work-system); this page says
where each record goes and what enforces it. Setting up a laptop is in [work-laptop-runbook.md](work-laptop-runbook.md).

One owner per fact. Every record has one home, and everything else links to it. The layout is the same for `suite-default` (Jira KAN and Confluence SD) and for `work-default` (the company's own Jira project and Confluence space). Each harness profile names its site and space, so the same skills work in both places and can't write to the wrong one.

## Where each record lives

| Record | Home | What it must carry |
| --- | --- | --- |
| A unit of work | Jira ticket under its project's epic | Goal, acceptance criteria, verify command, out of scope; an `exec:` and a `repo:` label |
| A question only you can answer | Jira Decision ticket that blocks the work, in Needs Decision | Options, Recommendation, Default if unanswered, Scope, Due; labels `decision`, `human-decision`, `exec:human`, `repo:`; assigned to you |
| The roadmap | Epics labelled `roadmap` | Goal, Milestone and Blocked by in the description, a `health:` label; shown on the Confluence Roadmap page |
| A decision that binds code | ADR in the repo's `docs/decisions/` | Linked from its Decision ticket |
| The long reasoning behind a decision | Confluence Second brain, Decision write-ups | A link to its Decision ticket |
| Notes, meeting notes, research | Confluence Second brain | One page per subject, linked to a ticket or epic |
| Process and architecture | Confluence Engineering OS and System architecture | Updated in place, never copied |
| Status, PRs, CI | Jira and GitHub | Never typed onto a page |
| Personal, business and content work | Notion Cabinet | No engineering content |

## What keeps it organized

Four layers do it. Skills tell agents where things go. Hooks block the worst mistakes during a session. The PR check fails a bad PR whoever opened it. Jira automation tidies up after people and agents, because agents never move a ticket's status.

| Layer | Piece | What it enforces | State |
| --- | --- | --- | --- |
| Skill | `work-start` (team-harness) | No edit before a ticket key; finds or files the ticket; keys the branch | Exists |
| Skill | `jira-ticket` and `ticket-template.md` | The definition of ready, plan and progress comments; agents never move status | Exists |
| Skill | `decision-ticket` | A question becomes a Decision that blocks the work; records your pick and lists what to move | Exists |
| Skill | `work-docs` | Which document goes where; pins the Confluence site and space; search before creating | Exists |
| Skill | `github-pr` | `Jira:` and `Docs:` lines; the merge rule for the harness | Exists |
| Skill | `release-approvals` (work-default) | Approval tickets for the org's merge gates | Exists |
| Skill | ai-dlc `document-organize`, `document-review` | Repo docs: catalog, placement, freshness | Exists |
| Skill | ai-dlc `day-start`, `day-end`, `review-inbox`, `handoff` | The daily rhythm over the tracker | Exists |
| Skill | `confluence-context` | Reads the page tree and the page that covers a subject before writing | New, KAN-303 |
| Skill | Second-brain capture | Files a note, meeting note or research page under the right parent, with ticket links | New, KAN-323 |
| Skill | Weekly hygiene sweep | One report of strays (the filters below); fixes only what you approve | New, to file |
| Hook | `guard_work_system.py` (team-harness) | Blocks keyless commits, keyless PRs or PRs without `Jira:` and `Docs:`, agent-set `exec:agent`, any agent status transition, and merges where the harness forbids them | Exists |
| Hook | ai-dlc plugin hook | Guards `docs/specs` edits and destructive shell commands | Exists |
| PR check | `actions/work-system-pr/check.py` | Key, `Jira:` and `Docs:` lines; ticket open, labelled and not blocked by an open Decision; work gates | Exists |
| Jira | Decision type, Needs Decision, Ready for agent and Wont Do statuses, Bug type | The shapes the skills write | Exists in KAN; set up per site |
| Jira | Decision fields Options, Recommendation, Default if unanswered, Scope | Filled by the skill | Exists in KAN; set up per site |
| Jira | Decision fields Chosen and Rationale | Where your pick is recorded | Exists in KAN; set up per site |
| Jira | Saved filters and one dashboard | What you look at (below) | New |
| Jira | Automation rules | Status moves and tidy-up (below) | New |
| Confluence | Space page tree with a Second brain section | Homes for pages | Exists in SD; set up per site |
| Confluence | Page templates: Decision write-up, Note, Meeting note | Every page starts with its ticket link | New |
| Work Copilot | `doctor` and its MCP server | Local attention view and evidence | Exists; no live Jira or Confluence source yet |

## Saved filters

Save each in Jira, and put the first two on one dashboard. The project key is `KAN` for `suite-default`; use your own elsewhere.

| Filter | JQL |
| --- | --- |
| Needs me | `project = KAN AND labels = human-decision AND statusCategory != Done` |
| Overdue decisions | `project = KAN AND issuetype = Decision AND statusCategory != Done AND due < now()` |
| No epic | `project = KAN AND parent is EMPTY AND issuetype not in (Epic, Decision) AND statusCategory != Done` |
| No labels to route on | `project = KAN AND issuetype != Epic AND statusCategory != Done AND (labels is EMPTY OR labels not in (exec:agent, exec:pair, exec:human, lane:agent, lane:pair, lane:human))` |
| Roadmap epics without health | `project = KAN AND issuetype = Epic AND labels = roadmap AND labels not in (health:green, health:yellow, health:red)` |

The last two use exact label lists. Adjust them if your `health:` values differ.

## Automation rules

Jira automation moves statuses, so no agent has to.

1. **Decision filed:** when a Decision is created, assign it to you, add `human-decision` if missing, and set Needs Decision.
2. **Decision answered:** when Chosen is filled on a Decision, move it to Done and comment on each ticket it blocks.
3. **Work unblocked:** when a Decision moves to Done and no open Decision still blocks the ticket, move that ticket from Needs Decision to To Do.
4. **Past due:** daily, comment "Due passed; the default applies unless you say otherwise" on each overdue Decision.
5. **Merged:** when the linked PR merges, move the ticket to Done. Skip this where hangar or `ai-dlc work finish` already moves it.

## Setting it up, in order

1. Save the five filters and the dashboard.
2. Create the five automation rules, one at a time, and test each on a scratch ticket.
3. Add the three Confluence page templates to the knowledge-base space.
4. Merge the open team-harness PRs for the work-system layer (7 to 11), so the skills and hook are current.
5. Do KAN-303 and KAN-323, then file and do the hygiene sweep.

At work, check the company project's Decision type has the same fields (KAN's include Chosen and Rationale), then repeat steps 1 to 3 in the company project and space. Automation there needs a Jira admin, so ask before you plan on it.
