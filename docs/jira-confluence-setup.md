# Jira and Confluence setup spec

How to build the Jira project and the Confluence space the work system needs, field by field and rule by rule.
[jira-confluence-organization.md](jira-confluence-organization.md) says where each record goes and what keeps it
there; this page says how to set up the tools so they can hold it. The live reference is KAN (Jira) and SD
(Confluence) on the personal site. The canonical model is
[cabinet `config/work-system/`](https://github.com/Sean-Koval/cabinet/tree/main/config/work-system)
(`model.toml`, `atlassian.toml`, `docs/WORK-SYSTEM-CONTRACT.md`); when this page and the model disagree, the model
wins and this page is fixed.

Nothing here copies content between sites. At work you rebuild the **structure** (types, fields, statuses, labels,
rules, page tree, templates) in the company's project and space. No ticket, page or label value from KAN or SD
goes to a work system, and nothing from work comes back.

Contents:

- [Part 1. Jira](#part-1-jira): project, work types, fields and screens, statuses and workflow, labels, links,
  automation, the hangar webhook, filters, dashboard, board.
- [Part 2. Confluence](#part-2-confluence): space, page tree, templates, page labels, permissions, page and ticket
  links.
- [Part 3. Who can do what](#part-3-who-can-do-what): what needs a Jira or Confluence admin at work.
- [Part 4. From KAN and SD to work](#part-4-from-kan-and-sd-to-work): the mapping, and the fallbacks when work
  can't have something.
- [Part 5. The work laptop](#part-5-the-work-laptop): Mac, Windows coworkers, and where the ESS work ops skill goes.
- [Part 6. Order of setup](#part-6-order-of-setup).

## Part 1. Jira

### J1. The project

| Setting | KAN (reference) | At work |
| --- | --- | --- |
| Style | Team-managed, one shared workflow for every work type | Usually company-managed; the steps below give both |
| Key | `KAN` | The team's key; the PR check and skills read it from the org overlay |
| Transitions | Global: any status to any status | Keep global for people; the session hook and automation keep agents in line |
| GitHub | GitHub for Jira app installed, not yet connected to the repos | The app connected to every repo the team ships, or automation A1 to A3 never fire |

### J2. Work types

| Type | KAN id | Purpose | Ticket template |
| --- | --- | --- | --- |
| Epic | 10006 | One per project (a roadmap epic, labelled `roadmap`) or per release | Roadmap epic |
| Story | 10009 | A user-visible change | Agent ticket or pair ticket |
| Task | 10008 | A distinct piece of work | Agent ticket or pair ticket |
| Bug | 10046 | Something that stops working as intended | Agent ticket or pair ticket |
| Decision | 10045 | One question only a person can answer; it blocks the work it holds up | Decision |
| Subtask | 10007 | A step of a larger item | free |

The templates are written out on SD's Templates page and in the contract, section 9. Two headings are read by
tools: hangar reads **Acceptance criteria** and **Verify command**. Rename them only together with hangar.

### J3. Fields and screens

**System fields, every type.**

| Field | Required | Notes |
| --- | --- | --- |
| Summary | Yes | On a Decision it is the question, one per ticket |
| Description | No (the templates fill it) | An agent ticket's Why, Scope, Acceptance criteria, Verify command, Context; an epic's Roadmap section |
| Labels | Convention (rule A8 flags a missing lane) | See J5 |
| Parent | Convention: every Story, Task and Bug sits under its project's epic | The "No epic" filter finds strays |
| Assignee | Decision: yes, the person who decides | Work tickets: whoever works it |
| Linked work items | Decision: links as *blocks* | See J6 |
| Priority | No | Only Sean sets it |
| Flagged | No | Not used by any tool |

**Decision fields** (custom). The IDs are KAN's; a new site mints its own, which go in the private org overlay.

| Field | KAN id | Type | Options | On create | On Done |
| --- | --- | --- | --- | --- | --- |
| Options | customfield_10100 | Paragraph (multi-line text) | - | Required | - |
| Recommendation | customfield_10101 | Paragraph | - | Required | - |
| Default if unanswered | customfield_10102 | Paragraph | - | Required | - |
| Scope | customfield_10104 | Select list (single choice) | Ticket, Project, Suite | Required | - |
| Due | customfield_10106 | Date picker | - | Required | - |
| Chosen | customfield_10105 | Short text (single line) | - | Hidden or optional | Required |
| Rationale | customfield_10103 | Paragraph | - | Hidden or optional | Required |

**One due field.** Decisions use the custom **Due**, not the system **Due date**. Some KAN Decisions (KAN-342 among the open ones) carry the system Due date instead, so filters miss them. Two consequences:

- In JQL write `cf[10106]`, never `due`: `due` is JQL's name for the system Due date.
- Copy the system date into Due on each open Decision that has one, then hide the system Due date on the Decision layout.

**Where the fields appear.**

- *Team-managed (KAN):* Project settings → Work types → Decision. Put Options, Recommendation, Default if unanswered,
  Scope and Due in the description area and mark them required; put Chosen and Rationale in the context area,
  optional. Team-managed projects can't require a field on a transition, so rule A5 checks Chosen before it moves
  anything.
- *Company-managed (work):* a Decision screen scheme with three screens.
  - *Create:* Summary, Options, Recommendation, Default if unanswered, Scope, Due, Description, Labels, Assignee,
    Linked work items.
  - *Edit and View:* the Create screen plus Chosen and Rationale.
  - *Transition to Done:* Chosen and Rationale, with a "Field required" validator on both.

The field configuration marks the five create fields required for the Decision type only.

**Epic fields.** None are custom. The lead routine rewrites a `## Roadmap` section in the description with four
lines: **Goal**, **Milestone**, **Blocked by** and **Swim lane** (Agent suite, Dev tooling or Product). A
`### Milestones to work use` list follows it. Nothing else reads the description.

### J4. Statuses and workflow

| Status | KAN id | Category | Board column | Meaning |
| --- | --- | --- | --- | --- |
| To Do | 10004 | To do | To Do | Filed, not ready for an agent |
| Ready for Agent | 10043 | To do | Ready for Agent | A `lane:agent` ticket that passes the Definition of ready; entering it starts a hangar job |
| In Progress | 10005 | In progress | In Progress | A person or a job is on it |
| Needs Decision | 10044 | In progress | Needs Decision | Started work an open Decision blocks, or an open Decision itself |
| In Review | 10006 | In progress | In Review | A PR with the key is open |
| Done | 10007 | Done | Done | The PR merged, or the decision was made |
| Wont Do | 10045 | Done | Done | Dropped, duplicated or superseded |

In a company-managed workflow, Done sets the resolution Done and Wont Do sets Won't Do (a post function on each
transition). A team-managed project does this itself.

**Who moves what.** Jira allows any move. The rules below are kept by automation, hangar and the session hook, and
no move is ever an agent's.

| From | To | Types | Moved by | When |
| --- | --- | --- | --- | --- |
| To Do | Ready for Agent | Story, Task, Bug | Sean (or the ticket owner at work) | `lane:agent` and the Definition of ready holds |
| To Do, Ready for Agent | In Progress | Story, Task, Bug, Subtask | A1, hangar, a person | A branch with the key exists, or a job started |
| In Progress, In Review | Needs Decision | Story, Task, Bug, Subtask | A4, hangar, a person | An open Decision blocks it |
| Needs Decision | Ready for Agent | Story, Task, Bug | A5, a person | Every blocking Decision is Done and the lane is agent |
| Needs Decision | In Progress | Story, Task, Bug, Subtask | A5, a person | Every blocking Decision is Done and the lane isn't agent |
| In Progress | In Review | Story, Task, Bug, Subtask | A2, hangar, a person | A PR with the key is open |
| In Review | In Progress | Story, Task, Bug, Subtask | hangar, a person | Changes requested, or the PR closed unmerged |
| Any open | Done | Story, Task, Bug, Subtask | A3, the lead routine, a person | A PR with the key merged |
| To Do | Needs Decision | Decision | A9 | On creation; it waits here |
| To Do, Needs Decision | Done | Decision | The decider only | Chosen and Rationale filled, `needs-sean` dropped |
| To Do, Done | In Progress | Epic | Sean | The project is active |
| In Progress | Done | Epic | Sean | The project or release is finished |
| Any | Wont Do | Any | A person | Dropped, duplicated or superseded; a superseded Decision links its replacement |
| Wont Do | To Do | Any | A person | Reopened |

Agents never transition a ticket: `guard_work_system.py` refuses the call. The PR check fails a PR while an open
Decision blocks its ticket.

### J5. Labels

Jira labels are flat strings, so each group is a prefix and "one per item" is a convention the skills and the lead
routine keep. Lowercase, no spaces.

| Group | Values | One per item | Required on | Meaning | Set by |
| --- | --- | --- | --- | --- | --- |
| `lane:` | `lane:agent`, `lane:pair`, `lane:human` | Yes | Story, Task, Bug, Decision | Who works it: a hangar job, Sean with a local agent, or Sean alone | Sean only for `agent`; agents file `pair` or `human` and never change a lane |
| `repo:` | `repo:<repo name>` | No | Work tickets and Decisions | Where the work lands | Whoever files it |
| `health:` | `health:on-track`, `health:at-risk`, `health:blocked`, `health:paused` | Yes | Roadmap epics | Health of the current milestone | The lead routine, Sean |
| `roadmap:` | `roadmap:now`, `roadmap:next`, `roadmap:later` | Yes | - | When an open item is expected to start | Sean |
| `release:` | `release:<name>`, e.g. `release:1.0` | No | - | The release an item belongs to | Sean |
| `sev:` | `sev:low`, `sev:medium`, `sev:high` | Yes | - | Severity of a bug or finding | Whoever files it |
| Markers | `roadmap` | - | Roadmap epics | A project's roadmap epic | Sean |
| | `decision` | - | Decisions | It is a decision | The `decision-ticket` skill |
| | `needs-sean` | - | Open Decisions | Waiting on Sean; dropped when answered | The skill; Sean drops it |
| | `human-decision` | - | Open Decisions | Sean's "decisions for me" view keys on it (Nov 8 convention) | The skill |
| | `proposed` | - | Agent-filed tickets | Filed by an agent, not accepted yet | The agent |
| | `needs-triage` | - | Tickets with no lane | Waiting for a lane | Rule A8 |
| | `security` | - | - | Touches security-relevant code; never `lane:agent` | Whoever files it |
| | `openspec` | - | Mirrored stories | Written by a repo's change mirror; the A1 to A3 rules skip it | The mirror |
| | `overdue` | - | Decisions past Due | Stops rule A7 commenting twice | Rule A7 |
| Topics | free words (`docs`, `ops`, `cost`) | No | - | Nothing reads them | Anyone |

Notes:

- **`lane:` or `exec:`.** KAN and the merged skills use `lane:`. team-harness PR 7 renames it to `exec:`. Set up
  whichever the merged skills use (today `lane:`) and never both on one ticket. The "No lane" filter accepts both
  until PR 7 settles it.
- **`human-decision` and `needs-sean` overlap.** cabinet lists `human-decision` as legacy, but your decisions view
  uses it. Keep both in KAN until you retire one.
- **Legacy labels** still on open KAN tickets (`S1`, `S2`, `bug`, and bare project names such as `hangar`) carry no
  meaning. Don't create them at work.

### J6. Link types

| Link | Outward / inward | Use |
| --- | --- | --- |
| Blocks | blocks / is blocked by | A Decision blocks the work it holds up; work blocks work |
| Duplicate | duplicates / is duplicated by | The duplicate goes to Wont Do |
| Relates | relates to | Related, no order; an agent's out-of-scope finding relates to the ticket it came from |

All three exist on every Jira site. Nothing else is needed.

### J7. Automation rules

Project settings → Automation → Create rule. Build each one on its own, publish it, run its test, and read its audit
log before the next. A9 is live in KAN; A1 to A8 are to set up. The five rules in the organization spec map onto
these: "Decision filed" is A9, "Decision answered" and "Work unblocked" are A5, "Past due" is A7 and "Merged" is
A3.

Smart values below use KAN's field IDs; at work, replace them with the site's.

**A1. Branch starts work**

- *Trigger:* Branch created (a DevOps trigger; needs GitHub for Jira connected to the repo).
- *Conditions:* Work item fields condition: Status is one of To Do, Ready for Agent. Labels does not contain
  `openspec`.
- *Actions:* Transition work item to In Progress.
- *Test:* on a scratch ticket in To Do, push branch `<KEY>-scratch` to a sandbox repo. It is In Progress within a
  minute. Push a second branch: nothing changes.

**A2. PR opens review**

- *Trigger:* Pull request created.
- *Conditions:* Status is not one of In Review, Done, Wont Do. Labels does not contain `openspec`.
- *Actions:* Transition to In Review. Add comment `PR: {{pullRequest.url}}`.
- *Test:* open a draft PR titled `<KEY>: scratch`. The ticket moves to In Review with one comment.

**A3. Merge closes the ticket**

- *Trigger:* Pull request merged.
- *Conditions:* Work type is not Decision. Labels does not contain `openspec`. Status category is not Done.
- *Actions:* Transition to Done. Add comment `Merged: {{pullRequest.title}} {{pullRequest.url}}`.
- *Skip it* where hangar or `ai-dlc work finish` already closes the ticket; the status condition makes it a no-op
  there anyway.
- *Test:* merge the scratch PR. The ticket is Done with the comment; a closed-unmerged PR leaves it alone.

**A4. A Decision blocks started work**

- *Trigger:* Work item linked, link type Blocks.
- *Conditions:* `{{issue.issueType.name}}` equals Decision (the Decision is the trigger issue, the blocked ticket is
  `{{destinationIssue}}`).
- *Actions:* Branch rule "For destination work item": if Status is one of In Progress, In Review, transition to
  Needs Decision and comment `Waiting on {{issue.key}}: {{issue.summary}}`.
- *Second branch:* links are often made from the blocked side ("is blocked by"). Add an If/else block for when
  the trigger issue is the blocked ticket and `{{destinationIssue.issueType.name}}` is Decision. It does the same
  to the trigger issue.
- *Test:* link a scratch Decision as blocking an In Progress scratch ticket, from each side in turn. Both move to
  Needs Decision. A To Do ticket stays put, because an open Decision already fails its Definition of ready.

**A5. A Decision answered releases the work**

- *Trigger:* Work item transitioned, to Done.
- *Conditions:* Work type is Decision. `{{issue.customfield_10105}}` is not empty. If it is empty, comment `Chosen
  is empty, so nothing it blocks was moved` and stop.
- *Actions:* Branch rule "For related work items: linked work items, link type blocks":
  - Condition: Status equals Needs Decision.
  - Condition (related work items): no other linked "is blocked by" item has type Decision and status category not
    Done.
  - If labels contain `lane:agent`: transition to Ready for Agent. Else: transition to In Progress.
  - Comment `{{triggerIssue.key}} decided: {{triggerIssue.customfield_10105}}`.
- *Test:* fill Chosen on the scratch Decision and move it to Done. The blocked ticket returns to In Progress with the
  comment. Repeat with two blocking Decisions: it moves only after the second.

**A6. A Decision is written up**

- *Trigger:* Work item transitioned, to Done.
- *Conditions:* Work type is Decision.
- *Actions:* Create Confluence page.
  - Space: SD (the team space at work). Parent: Decision write-ups (5341202 in SD).
  - Title: `{{issue.key}}: {{issue.summary}}`.
  - Body: the Decision write-up template (C3), with `{{issue.customfield_10100}}` (Options),
    `{{issue.customfield_10101}}` (Recommendation), `{{issue.customfield_10105}}` (Chosen) and
    `{{issue.customfield_10103}}` (Rationale).
  - Then add comment `Write-up: {{createdPage.url}}`.
- *Needs:* the automation user can add pages in the space (C5).
- *Test:* close the scratch Decision. One page appears under Decision write-ups, its fields filled. The ticket gets
  the link.

**A7. A Decision passes its Due**

- *Trigger:* Scheduled, daily at 09:00, JQL
  `project = KAN AND issuetype = Decision AND statusCategory != Done AND cf[10106] < now() AND (labels is EMPTY OR labels != overdue)`.
  (cabinet's `atlassian.toml` writes `Due < now()`, which JQL reads as the system Due date; fix it there to match.)
- *Actions:* Add comment `Due passed on {{issue.customfield_10106}}. The default applies unless you answer:
  {{issue.customfield_10102}}`. Add label `overdue`.
- *Test:* set a scratch Decision's Due to yesterday and use "Run rule". It gets one comment and the label; a second
  run adds nothing.

**A8. Every ticket has a lane**

- *Trigger:* Work item created.
- *Conditions:* Work type is one of Story, Task, Bug. Advanced compare: `{{issue.labels.match("^lane:.*")}}` is
  empty.
- *Actions:* Add label `needs-triage`. Add comment `No lane yet: add lane:pair or lane:human, or lane:agent if it
  meets the Definition of ready.`
- *Test:* create a scratch Task with no labels (flagged), then one with `lane:pair` (left alone).

**A9. A new Decision waits for its decider** (live in KAN)

- *Trigger:* Work item created.
- *Conditions:* Work type is Decision.
- *Actions:* Transition to Needs Decision.
- *Optional additions,* your call since the rule is live: if Assignee is empty, assign to you; if labels don't
  contain `human-decision`, add it.
- *Test:* create a scratch Decision. It opens in Needs Decision.

**Clean up after testing.** Move every scratch ticket to Wont Do and archive the scratch write-up page.

### J8. The hangar webhook

Moving a `lane:agent` ticket into Ready for Agent starts one hangar job. Two ways to wire it:

- *A Jira webhook* (Settings → System → WebHooks, needs a Jira admin): event Work item updated, JQL
  `project = KAN AND status = "Ready for Agent" AND labels = lane:agent`, URL hangar's Jira door.
- *An automation rule* (project admin is enough): trigger transitioned to Ready for Agent, condition labels contain
  `lane:agent`, action Send web request (POST, body "Work item data") to hangar's Jira door. The shared secret goes in
  the action's secret header field, never in the rule's text or this repo.

At work this waits on the decision about hangar (KAN-356: trace import only for now), so set up neither yet.

### J9. Filters

Save each one (Filters → Save filter), shared with yourself only.

| Filter | JQL |
| --- | --- |
| Needs me | `project = KAN AND labels = human-decision AND statusCategory != Done` |
| Overdue decisions | `project = KAN AND issuetype = Decision AND statusCategory != Done AND (cf[10106] < now() OR duedate < now())` |
| Blocked by a decision | `project = KAN AND status = "Needs Decision" AND issuetype != Decision` |
| Ready for an agent | `project = KAN AND status = "Ready for Agent" ORDER BY rank` |
| Needs a lane | `project = KAN AND issuetype in (Story, Task, Bug) AND statusCategory != Done AND (labels = needs-triage OR labels is EMPTY OR labels not in (lane:agent, lane:pair, lane:human, exec:agent, exec:pair, exec:human))` |
| No epic | `project = KAN AND parent is EMPTY AND issuetype not in (Epic, Decision, Subtask) AND statusCategory != Done` |
| Proposed by agents | `project = KAN AND labels = proposed AND statusCategory != Done ORDER BY created DESC` |
| Stale in review | `project = KAN AND status = "In Review" AND updated < -7d` |
| Merged but open | `project = KAN AND statusCategory != Done AND development[pullrequests].all > 0 AND development[pullrequests].open = 0` |
| Roadmap epics without health | `project = KAN AND issuetype = Epic AND labels = roadmap AND labels not in (health:on-track, health:at-risk, health:blocked, health:paused)` |

`labels not in (...)` skips tickets with no labels at all, which is why "Needs a lane" adds `labels is EMPTY`. Drop the `duedate` half of "Overdue decisions" once those dates are copied (J3). "Merged but open" works
only once GitHub for Jira is connected to the repos.

### J10. Dashboard

One dashboard, "Work system", private to you.

| Gadget | Filter or source | Setting |
| --- | --- | --- |
| Filter results | Needs me | Columns: Key, Summary, Due, Assignee |
| Filter results | Overdue decisions | Columns: Key, Summary, Due |
| Filter results | Blocked by a decision | Columns: Key, Summary, Status, Linked work items |
| Two-dimensional filter statistics | Open work (`project = KAN AND statusCategory != Done`) | X: Status; Y: Labels |
| Filter results | Needs a lane | Columns: Key, Summary, Created |
| Filter results | Merged but open | Columns: Key, Summary, Status |

### J11. Board

| Column | Statuses |
| --- | --- |
| To Do | To Do |
| Ready for Agent | Ready for Agent |
| In Progress | In Progress |
| Needs Decision | Needs Decision |
| In Review | In Review |
| Done | Done, Wont Do |

Group by epic, so each project is a swimlane. Add four quick filters: Only mine (`assignee = currentUser()`),
Decisions (`issuetype = Decision`), Agent lane (`labels = lane:agent`) and one per busy repo (`labels = repo:hangar`).
Color cards by work type, so Decisions stand out in Needs Decision.

## Part 2. Confluence

### C1. The space

| Setting | SD (reference) | At work |
| --- | --- | --- |
| Space | Software Development, key `SD` | The team's space, or a new one if you may create spaces |
| Home page | Links to Engineering OS, Roadmap and Second brain | The same three links |
| Starter pages | Template - Decision documentation, Template - Meeting notes, Template - Product requirements (Confluence's samples) | Don't create them; archive them in SD when you like |

### C2. The page tree

Create the pages in this order, each under its parent. The ID is SD's.

```text
<Space home>                          360628
├── Engineering OS                    5111810   how work flows: lanes, statuses, ready and done
│   └── Templates                     5177361   every ticket, PR, ADR and page template, copied from the contract
├── System architecture               5275650   how the projects fit together; updated in place
├── Specs index                       5046274   one row per spec: link to the repo file and its epic
├── Roadmap                           5242882   a Jira issues macro, nothing typed
└── Second brain                      5308417
    ├── Notes                         5242901   one page per subject
    ├── Meetings                      5373953   one page per meeting
    ├── Research                      5341186   one page per question
    └── Decision write-ups            5341202   written by rule A6 only
```

What each page holds:

- **Roadmap:** a Jira issues macro with JQL `project = KAN AND issuetype = Epic AND labels = roadmap`. Show the
  columns Key, Summary, Status and Labels.
- **Specs index:** a table with a Spec, Repo file and Epic column, one row per spec. The spec itself stays in its
  repo.
- **Decision write-ups:** a Page Properties Report over label `decision-writeup`, columns Ticket, Chosen and Date.
  Each write-up's page properties feed it.
- **Meetings and Research:** the same report over labels `meeting` and `research`.

### C3. The page templates

Create them as space templates (Space settings → Templates → Create template; needs space admin). Each starts with
the ticket link, because the ticket is the record and the page explains it.

**Decision write-up.** Title `<KEY>: <question>`. Labels `decision-writeup`, `repo-<name>`. Rule A6 fills it; nobody
writes one by hand.

```markdown
| Ticket | <Jira link to KEY> |
| Chosen | <Chosen> |
| Date | <date answered> |
(a Page Properties macro around this table)

## Question
<the Decision's summary>

## Options
<Options>

## Recommendation
<Recommendation>

## Chosen
<Chosen>

## Rationale
<Rationale>

## Links
- Decision ticket: <KEY>
- ADR, if the call binds code: <repo path docs/decisions/NNNN-slug.md>
- Work it unblocked: <keys>
```

**Meeting note.** Title `YYYY-MM-DD <subject>`. Labels `meeting`, plus `repo-<name>` when it concerns one repo.

```markdown
| Date | <date> |
| Epic or ticket | <Jira link> |
(a Page Properties macro around this table)

## Attendees
- @person

## Notes
- what was said, briefly

## Decisions
- <what was decided>: <Decision key, or "filed as KEY">

## Action items
- [ ] <action> (@owner, <KEY>)
```

Every decision taken links its Decision ticket, or a new Decision is filed. Every action item names its ticket key;
an action with no ticket gets one filed as `proposed`.

**Note.** Title: the subject. Label `note`, plus `repo-<name>` where it fits.

```markdown
Related: <Jira link to the ticket or epic>

<free form: one page per subject>

## Links
- <tickets by key, pages, repo files>
```

Link tickets by key; never restate their status, because the ticket shows it live.

**Research** (a fourth, already on SD's Templates page). Title: the question. Label `research`.

```markdown
| Ticket or epic | <Jira link> |
| Date | <date> |
(a Page Properties macro around this table)

## Question
## Findings
## Sources
## Recommendation
## Follow-up
- <proposed ticket KEY>
```

Every claim has a source. Follow-up work is filed as `proposed` tickets and linked by key.

### C4. Page labels

Confluence labels can't hold a colon, so the Jira `repo:` prefix becomes `repo-` here.

| Label | On |
| --- | --- |
| `decision-writeup` | Every page under Decision write-ups |
| `meeting` | Every page under Meetings |
| `research` | Every page under Research |
| `note` | Every page under Notes |
| `repo-<name>` | Any page about one repo |
| `architecture`, `process` | System architecture, Engineering OS and their children |

### C5. Permissions

| Who | SD | At work |
| --- | --- | --- |
| You | Space admin | Edit; space admin if the team lets you, for templates |
| Team | - | View and edit, as the space already grants |
| Anonymous | Off | Off |
| Automation for Jira (rule A6) | Add pages | Add pages, or A6 fails silently |
| Agents (Atlassian MCP, as you) | Your rights | Your rights |

Restrict editing of Decision write-ups to you and the automation user, so the generated pages stay generated.

### C6. How pages and tickets link

- **Page to ticket:** the first line of every page is a Jira smart link to its ticket or epic, as the templates do.
- **Ticket to page:** Jira lists a page under the ticket's Confluence section once the page links the ticket. Rule
  A6 and the skills also comment the page URL on the ticket.
- **Live views:** the Roadmap page and the reports in C2 are macros over JQL or labels. Never type a status onto a
  page.
- **Repo to page:** a PR that changes a page names it on its `Docs:` line.

## Part 3. Who can do what

| Step | KAN and SD | At work |
| --- | --- | --- |
| Decision work type, its seven fields, screens | You (project admin, team-managed) | **Jira admin** (company-managed schemes) |
| Ready for Agent, Needs Decision, Wont Do statuses | You | **Jira admin** (workflow) |
| Automation A1 to A9 | You (project admin) | **Project admin**; many companies restrict automation, so ask first |
| hangar webhook | You (site admin) | **Jira admin** for a system webhook; project admin for the automation route |
| GitHub for Jira connected to repos | You | **Jira admin** plus a **GitHub org owner** |
| Remote Atlassian MCP allowed | You | **Atlassian org admin** |
| Read-only account for the PR check | You | **Jira admin** creates the account; its token is a CI secret |
| Filters, dashboard, labels, quick filters | You | You (quick filters need board admin) |
| Space, page tree, page labels | You | You, with edit rights in the space |
| Space templates and space permissions | You (space admin) | **Space admin** |

Without any admin at work, you can still have the filters, dashboard, labels, page tree and pages. The Decision type
falls back to a Task (Part 4), and the status moves stay manual, by you.

## Part 4. From KAN and SD to work

| KAN and SD | At work | If work can't have it |
| --- | --- | --- |
| Project KAN | The team's project and key, in `org.yaml` `params.tracker` | - |
| Decision work type | A Decision type with the same seven fields | A Task labelled `type:decision`, with Options, Recommendation, Default and Due as description headings; `work-default` files it this way |
| Chosen and Rationale fields | The same fields | Description headings filled when answered |
| Ready for Agent | The same status | Leave it out until hangar runs at work |
| Needs Decision | The same status | The team's Blocked status, or Flagged plus a `blocked-by-decision` label |
| Wont Do | The same status | The workflow's Won't Do resolution |
| `lane:` labels | The same labels | - |
| `human-decision`, `needs-sean` | `decision` plus the decider as assignee; "Needs me" filters on `assignee = currentUser()` | - |
| Automation A1 to A9 | The same rules, with the site's field IDs | Moves stay manual; the PR check still blocks a PR behind an open Decision |
| Space SD | The team's space, in `org.yaml` `params.kb_site` and `params.kb_space` | Your personal space at work, never SD |
| Second brain | A Second brain subtree in that space | - |
| Field IDs, page IDs | Recorded in the private fork's org overlay, the way cabinet's `atlassian.toml` records KAN's | - |

`work-default` already behaves as the right-hand column: Decisions as `type:decision` Tasks, assigned to the ticket
owner, `merge_mode: never`, and site and space left as placeholders until the private overlay sets them.

## Part 5. The work laptop

- **Mac.** The work laptop is a Mac, so `work-default`, ai-dlc, hangar's trace import and flightdeck run natively
  (KAN-370). Install the Xcode Command Line Tools first; the hooks call `python3`.
- **Windows coworkers.** Keep the Work Copilot Windows keyring fix in scope. Its Windows CI fails three OAuth
  storage tests today, and teammates on Windows hit that path. They run ai-dlc in WSL2 where policy allows it.
- **The ESS work ops skill** lives on your work computer. Copy it into your private fork on that laptop, at
  `orgs/<company>/skills/org-process/` (`SKILL.md` and anything it references). `install_local.py` then installs it
  into the work repo with the rest of `work-default`. It never goes into this public repository, KAN or SD. The ESS
  review step is a gate a person files, triggered by a ticket label (KAN-355), so name that label in
  `orgs/<company>/org.yaml`.

## Part 6. Order of setup

**In KAN and SD (you, today):**

1. Copy system Due dates into Due on open Decisions and fix rule A7's JQL in cabinet (J3, J7).
2. Save the ten filters and build the dashboard and board (J9 to J11).
3. Connect GitHub for Jira to the repos, then build A1, A2 and A3 and test each.
4. Build A4 to A8 and test each; decide whether A9 gets its two optional additions.
5. Create the three page templates and the label reports in SD; grant the automation user Add page (C2 to C5).
6. Clean up the scratch tickets and pages.

**At work (after asking the admins in Part 3):**

1. Map each row of Part 4, and write the site's project key, space and field IDs into the private overlay.
2. Ask a Jira admin for the Decision type and fields, or use the Task fallback.
3. Save the filters and dashboard against the company project.
4. Build the page tree and templates in the team space.
5. Ask the project admin about automation; build A9, A5 and A3 first, the three that save the most clicks.
6. Copy the ESS skill into the private overlay and run the first test ticket from the runbook.
