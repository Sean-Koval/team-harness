# Capture: what goes in, and how to say it

Capture is deliberately narrow. Only three kinds of source reach the knowledge repository's `inbox/`, and an agent
proposes records from each one as a pull request. Nothing becomes a record until a person merges it.

## What is captured

| Source | How it reaches the inbox | State today |
| --- | --- | --- |
| Lines you mark with `>>` in your work notes | `work-copilot export` writes them as one Source per day | On main |
| Rooms you picked in Work Copilot | Work Copilot's collector reads only allow-listed rooms; export writes them | Collector not yet qualified against the live chat server (KAN-462) |
| Recorded meetings | A transcript provider lands the transcript (KAN-457); the [nightly batch](#the-nightly-batch) proposes records (KAN-458) | Both on main, neither tried against a live meeting account yet. You schedule the batch yourself (no cloud runner until KAN-432) |

Everything else stays out: unmarked note lines, rooms you did not pick, meetings nobody recorded, and direct
messages. Raw payloads in `inbox/` and `processed/` are deleted after 30 days: a nightly job in the knowledge
repository opens the deletion PR, and a person merges it. The Source record and the records made from it stay.

## The nightly batch

One job pulls cheaply and extracts once a day, so token use stays predictable (decision KAN-420). Each run:

1. pulls new transcripts (`ai-dlc knowledge pull-transcripts`) and, when Work Copilot is installed, exports picked
   rooms and marked notes (`work-copilot export`). Each reaches 48 hours behind its last pull, so a thread collected
   late still arrives;
2. sets aside chat threads with fewer than 5 messages and no decision word (decided, agreed, going forward, we will).
   Their Source records move from `inbox/` to `processed/` unchanged;
3. runs `extract-records` once per remaining Source, one Claude Code session each, on a throwaway copy of the
   repository. The batch then proposes what the session wrote as one draft records PR. Nothing merges.

A Source whose session finished moves to `processed/` too, so `inbox/` holds only what is left. The run stops before
it would pass the nightly token ceiling and lists the Sources it left. The next run starts with them. A Source of any
other kind, such as a ticket export, waits in the inbox for `process-now`. So does a Source whose session wrote no
records: the run lists it under `no_pr`, and later runs skip it until a person looks.

Run these from your project, with this harness cloned where the [quickstart](quickstart.md) put it. macOS:

```sh
python3 ~/src/team-harness/scripts/capture_batch.py run --repo "$KNOWLEDGE_REPO" --dry-run   # writes nothing
python3 ~/src/team-harness/scripts/capture_batch.py run --repo "$KNOWLEDGE_REPO"
python3 ~/src/team-harness/scripts/capture_batch.py process-now <source id> --repo "$KNOWLEDGE_REPO"
```

Windows (untested):

```powershell
py -3 $HOME\src\team-harness\scripts\capture_batch.py run --repo $env:KNOWLEDGE_REPO --dry-run
py -3 $HOME\src\team-harness\scripts\capture_batch.py run --repo $env:KNOWLEDGE_REPO
py -3 $HOME\src\team-harness\scripts\capture_batch.py process-now <source id> --repo $env:KNOWLEDGE_REPO
```

Your project is the ai-dlc project that configures the knowledge and transcripts roles, with the harness installed
at project scope; pass `--project <dir>` to run from elsewhere. `process-now` extracts one Source at once, including
a thread the filter set aside. Schedule `run` nightly with cron, launchd or Task Scheduler, on a machine signed in to Claude Code and
GitHub.

Each session runs restricted: it loads no user, project or local settings, no skills and no MCP servers. The batch
gives it its rules and the `extract-records` instructions itself. Its only folder is a throwaway copy of the knowledge
repository, without `.git`, `.claude/`, `CLAUDE.md` or symlinks, in any letter case. There it may read and write
records, run `ai-dlc knowledge check` on the copy and print record templates. It cannot read your project, propose, push, or use `gh`, `git` or web tools.
One run holds the lock at a time; a run that was killed releases it.

The batch proposes what the session wrote from your project, as a draft PR on a `records-` branch. Records reach the
default branch only when a person merges that PR. The PR body lists any existing record the session
changed beyond marking it superseded, and an `@name` in it notifies nobody. To check the lockdown on your machine, run
`python3 ~/src/team-harness/scripts/capture_smoke.py` once; it costs one short session.

Each run appends a line to `capture/runs.jsonl` in the knowledge repository's working tree, in ai-dlc's capture run
format (`contracts/capture-run.schema.json`). It lists each Source filtered, extracted, failed or left at the ceiling,
with tokens, cost and its draft PR. Usage nobody reported, such as a failed session's, is left unknown rather than 0. A transcript also carries its length, so `ai-dlc knowledge stats` can give a cost
per transcript hour. It holds Source ids, never titles, paths or pull output, which go only to the terminal.
The batch commits and pushes nothing; records reach the repository only through their PRs. `capture/state.json` remembers every Source by its hash, so a second run with nothing new
makes no model call. Tune the filter and the ceiling in `knowledge.toml`:

```toml
[capture]
token_ceiling = 1000000          # per run
min_messages = 5
decision_words = ["decided", "agreed", "going forward", "we will"]
chat_providers = ["*chat*", "slack*", "teams*", "symphony*"]   # which Source providers are chat
scope = "team"                   # work-copilot export --scope
owner = "your-login"             # work-copilot export --owner; default: [transcripts] owner
```

The commands it runs and the tools a session may use are fixed in the script, not read from the repository.

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
  payload at once, without waiting for the 30-day deletion PR.

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
