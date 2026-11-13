---
name: knowledge-howto
description: Use when a teammate asks how to use the knowledge system itself ("how do I get my first record", "how do I say a decision so it's captured", "how do I opt a meeting out", "how do I review a records PR", "how do I find why we decided X"). Answers from the teammate guide, names the page and section, and never invents a step. Read-only.
allowed-tools: Read, Grep, Glob
---

# How do I… (the knowledge system)

Answer questions about *using* the knowledge system from the teammate guide: `docs/knowledge/` in the team's copy of
the harness repository. The quickstart has every teammate clone that repository beside their work repository (for
example `../team-harness`). When a clone is at hand, read the page for the exact commands. When it is not, answer
from the map below and name the page and section to read.

{{wall}}

Never run, propose, approve or merge anything from this skill. To find what a record says, use `query-knowledge`; to
see what is open on a project, use `whats-next`.

## Map: question → page, section, short answer

| Question | Page, section | Short answer |
| --- | --- | --- |
| How do I get my first record? | `quickstart.md`, all six steps | Install the harness, set `KNOWLEDGE_REPO`, copy the sample meeting into the inbox, run `extract-records`, review the draft PR, merge it. About 15 minutes |
| How do I install the harness? | `quickstart.md`, 1 | `scripts/install_local.py` previews, `--apply` writes, `--check` prints `clean`; `--uninstall` removes what it wrote |
| How do I check the guard hook works? | `quickstart.md`, 2 | In a scratch repository on `main`, ask the session to commit; the hook refuses with `blocked by the work-system hook` |
| What gets captured? | `capture.md`, What is captured | Only `>>` note lines, rooms the person picked, and recorded meetings. Nothing else. Policy deletes raw payloads after 30 days, by hand until a job does it |
| How do I mark a note line? | `capture.md`, Mark note lines | Start the line with `>>`, then export it to the knowledge clone and run `extract-records` |
| How do I say a decision so it is captured? | `capture.md`, Say a decision | One sentence starting "Decided:" with the whole choice in it. Actions name an owner and a date. To change a decision, say what it replaces |
| How do I opt a meeting out? | `capture.md`, Opt a meeting out | No switch yet: don't record it, don't pick its room, don't mark its notes. If a Source arrives anyway, tell the convention owner and close its PR unmerged |
| What about customer meetings? | `capture.md`, Customer meetings | Only to that customer's own knowledge repository, never the team's. Until that repository exists, don't capture them |
| How do I review a records PR? | `review.md`, all sections | Read the body's Flags first, then check each record's type, status, scope, evidence quote, owner and date against the Source |
| Fix, drop or duplicate? | `review.md`, Fix, drop or mark a duplicate | Fix a wrong field; drop anything without an exact quote; delete a duplicate and name the existing id. A change to a decision is a new decision that supersedes it |
| Can I approve my own records PR? | `review.md`, Approve and merge | No. Mark it ready, have a teammate approve, merge when the knowledge check is green |
| Why did we decide X? | `find.md`, Ask in a session | Ask the session (`query-knowledge`), or `ai-dlc knowledge records search`, then `ai-dlc knowledge why <id>` for the chain. If ai-dlc has no `why`, follow `supersedes` and `superseded_by` with `records get` |
| What does a status mean? | `find.md`, Read what you find | `accepted` and `active` bind; `proposed` does not yet; `superseded` is history; `retracted` was accepted by mistake and never counts |
| Can I edit the wiki page? | `find.md`, The wiki view | No. The render job overwrites it; change the record by pull request |
| What isn't working yet? | `README.md`, What is not on main yet | Read the table there; never promise a step it lists as open |

## How to answer

1. Find the row. If a clone of the harness repository is at hand, read that page's section before answering.
2. Answer in two or three sentences, then name the page and section, such as "`quickstart.md`, step 3".
3. For commands, give the asker's system: the macOS block or the Windows (PowerShell) block, copied from the page,
   never written anew. The guide marks its Windows blocks untested end to end; say so.
4. Words in double curly braces on a page are the team's own values. Use the session's value when it has one (for
   example `KNOWLEDGE_REPO`); otherwise say which value is needed and that whoever set up the harness has it.
5. If the guide has no answer, say so in one line, suggest asking whoever owns team conventions, and note that the
   question belongs in the guide. Never make up a step.
