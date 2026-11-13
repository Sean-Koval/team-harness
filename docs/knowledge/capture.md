# Capture: what goes in, and how to say it

Capture is deliberately narrow. Only three kinds of source reach the knowledge repository's `inbox/`, and an agent
proposes records from each one as a pull request. Nothing becomes a record until a person merges it.

## What is captured

| Source | How it reaches the inbox | State today |
| --- | --- | --- |
| Lines you mark with `>>` in your work notes | `work-copilot export` writes them as one Source per day | On main |
| Rooms you picked in Work Copilot | Work Copilot's collector reads only allow-listed rooms; export writes them | Collector not yet qualified against the live chat server (KAN-462) |
| Recorded meetings | A transcript provider lands the transcript (KAN-457); a nightly batch proposes records (KAN-458) | Not built. Until then, a person places a transcript by hand |

Everything else stays out: unmarked note lines, rooms you did not pick, meetings nobody recorded, and direct
messages. Raw payloads in `inbox/` and `processed/` are deleted after 30 days. The Source record and the records
made from it stay.

## Mark note lines with `>>`

Start a line with `>>` in a note inside your Work Copilot folder. Only those lines leave your machine. Then export
them to your clone of the knowledge repository.

macOS:

```sh
work-copilot capture ~/work-notes
work-copilot export --to "$KNOWLEDGE_REPO" --since 2026-11-01T00:00:00+00:00 --owner "$ME" --scope team
```

Windows (untested):

```powershell
work-copilot capture $HOME\work-notes
work-copilot export --to $env:KNOWLEDGE_REPO --since 2026-11-01T00:00:00+00:00 --owner $me --scope team
```

Export writes files and never commits, pushes or calls another system. Run `extract-records` on the new inbox file,
as in the [quickstart](quickstart.md#4-extract-the-records).

## Say a decision so it is captured

The agent records only what someone said in so many words. It needs one sentence it can quote exactly. Say these
out loud in a recorded meeting, or write them as `>>` lines:

| To record | Say | Not |
| --- | --- | --- |
| A decision | "Decided: runbooks live in the service repository, not the wiki." | "Let's probably move them at some point." |
| An action | "I'll move the three runbooks by Friday the 20th." | "Someone should move them." |
| A question | "Question for `{{convention_owner}}`: do the wiki pages stay as redirects?" | "Not sure about the wiki pages." |
| No decision | "Not decided yet; we'll pick next week." | Silence, which reads as agreement |

Start a decision with "Decided:" and put the whole choice in the same sentence. Background and reasons can follow;
they go into the record's body. A rule repeated from an earlier decision makes no new record. To change a decision,
say what replaces it: "Decided: this replaces the Tuesday release rule."

An action with no named owner is still recorded, with owner `unknown`, and flagged in the PR for a reviewer to fix.

## Opt a meeting out

There is no opt-out switch in the tools yet. KAN-450 must approve how opt-out works before teammates' meetings are
captured. Until then:

- don't record the meeting, or don't pick its room;
- don't mark its notes with `>>`;
- if a Source arrives anyway, tell `{{convention_owner}}`. Close its records PR unmerged. A PR can delete the raw
  payload before its 30 days run out.

Ask everyone in a recorded meeting whether it may be captured. Whether participants must be told is part of the
KAN-450 sign-off.

## Customer meetings

What you learn inside a customer's systems stays with that customer. Its Sources and records go to that customer's
own knowledge repository, `{{customer_repo}}`, never to `{{knowledge_repo}}`. Creating one is open work (KAN-475);
until it exists, don't capture customer meetings.

In a customer repository, records are `scope: project` with `boundary: customer`, under `projects/<customer>/`.
`ai-dlc knowledge check` refuses a customer record outside its project. It also refuses a link to it from outside, and
any other record that repeats eight or more of its words in a row.

When `export` runs, check `--to` before anything else: it decides which repository the Source lands in. A lesson
worth sharing with the team is rewritten by a person as a new team Source that names no customer.
