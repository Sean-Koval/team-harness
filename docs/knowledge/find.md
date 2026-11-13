# Find out why we decided something

Every merged decision cites the Source it came from and quotes the sentence it rests on. So "why did we decide X"
has an answer you can check. Start in a Claude Code session, and drop to the command line when you want the raw
record.

## Ask in a session

With the harness installed (see the [quickstart](quickstart.md)), ask the question in plain words:

```text
Why did we decide to keep runbooks in the service repository?
What's open on the svc project?
```

The `query-knowledge` skill searches record headers and text, reads the matching records and cites their ids. The
`whats-next` skill lists a project's open questions, proposed decisions and unowned actions. Both ship in the
harness's `candidate` channel (#32). On `stable`, or outside a session, use the commands below.

## Search from the command line

`KNOWLEDGE_REPO` names your clone. Add `--provider git` when the current directory has no `ai-dlc.toml` that selects
the knowledge role.

macOS:

```sh
git -C "$KNOWLEDGE_REPO" pull
ai-dlc knowledge records search --provider git --type decision --status accepted --text "runbooks"
ai-dlc knowledge records get --provider git DEC-0012
```

Windows (untested):

```powershell
git -C $env:KNOWLEDGE_REPO pull
ai-dlc knowledge records search --provider git --type decision --status accepted --text "runbooks"
ai-dlc knowledge records get --provider git DEC-0012
```

`search` prints JSON: each item's `id`, its `path` and its header. Start narrow, with one type, one status and one or
two distinctive words. `get` takes a numbered id or the slug the record had as a draft, and prints the body.

## Read what you find

- An `accepted` decision and an `active` convention bind. A `proposed` decision does not yet.
- A `superseded` decision is history. The `superseded_by` column of its directory's `index.md` names its successor.
- A `retracted` decision was accepted by mistake. A later decision `retracts` it and says why; `retracted_by` in the
  index names that decision. Treat it as never accepted.
- The quote at the top of the body is the evidence. The `sources` entry names the Source record it came from.
- The raw transcript or thread is deleted after 30 days. The Source record and the quote stay.

## Reconstruct a decision with `knowledge why`

`ai-dlc knowledge why <id>` prints the decision and the chain of what it replaced and what replaced it, and any
decision that retracts it. Each step comes with its reason and its quotes. It also lists linked conventions,
lessons and tickets. For each Source, it says whether the raw payload is still present or already deleted.

```sh
ai-dlc knowledge why DEC-0012
```

If your ai-dlc has no `knowledge why` yet, follow `supersedes` and `superseded_by` by hand with `records get`.

## The wiki view

The records are rendered into `{{wiki_space}}` for people who don't use git. Read it there, but never edit it: the
render job overwrites every page from the records. To change what a page says, change the record by pull request.

## When nothing matches

Say so: "no record covers X". Don't rebuild a decision from memory. If the choice was never made, raise it as a
question in a recorded meeting or a `>>` line ([capture.md](capture.md)), or as a Decision ticket.
