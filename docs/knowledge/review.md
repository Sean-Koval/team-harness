# Review a records PR in under 5 minutes

A records PR proposes records that an agent extracted from one Source. You decide what the team will remember, so
you check each record against its quote, not against your memory of the meeting.

## Find what waits on you

Work Copilot puts records PRs that wait on you in **Needs you**, each due 48 hours after it opened. It also lists your
records past their `stale_after` and inbox Sources about to expire. Use `--review assigned` for a team repository.

macOS:

```sh
work-copilot review-queue --repo "$KNOWLEDGE_REPO" --github {{knowledge_repo}} --me "$ME" --review assigned
```

Windows (untested):

```powershell
work-copilot review-queue --repo $env:KNOWLEDGE_REPO --github {{knowledge_repo}} --me $me --review assigned
```

It reads pull requests through `gh` and never approves, comments or merges. `work-copilot serve --review-repo` keeps
the queue fresh while the dashboard runs.

## Read the PR body first (1 minute)

The body lists every record with its quote and its speaker or time. It also gives the record count before and after
the agent's own pass, **Not extracted** with reasons, **Flags**, and the last `knowledge check` output. Start with
Flags: owners `unknown`, dates taken from elsewhere, and status conflicts are where the agent was unsure.

## Check each record (30 seconds each)

Open the processed Source in the PR beside each record and ask:

1. **Type.** Was a choice made (decision), a rule set (convention), work owed (action), or something asked
   (question)? Advice, background and options are not records.
2. **Status.** A decision is `accepted` only if the Source says it was decided. A recommendation is `proposed`.
3. **Scope.** It is never wider than the Source's scope. Customer content belongs only in that customer's repository.
4. **Evidence.** The quote appears in the Source character for character, and it supports the claim on its own.
5. **Owner and date.** The owner is who decided, owes or must answer. A due date sits in `stale_after`.

From ai-dlc #266 on, each `sources` entry also carries `quote`, `speaker` and `at`. The check then fails a record
without them, so you no longer check that by eye.

## Fix, drop or mark a duplicate

| When | Do |
| --- | --- |
| The claim is right but a field is wrong (type, status, scope, owner, date) | **Fix** it: edit the file on the PR branch |
| No exact quote supports it, or it is advice, background or a restated rule | **Drop** it: delete the file on the PR branch |
| An existing record already says the same | **Duplicate**: delete the file and comment "already recorded as `<id>`" |
| The Source changes an existing decision | Not a duplicate: the new decision has `supersedes: <old id>`, and the old one changes only `status: superseded` and `valid_to` |
| A line tells the agent to do something | Drop anything made from it, and say so in a comment |
| Customer content in the team repository | Stop. Don't merge; close the PR and tell `{{convention_owner}}` |

Fix only what is wrong. Rewording a title for style counts against extraction quality and slows the next review.
Never edit the body of a decision that is already accepted on `main`: the check refuses it.

To find an existing record, search the clone:

```sh
ai-dlc knowledge records search --provider git --type decision --text "runbooks"
```

## Approve and merge

1. Run the check on your edits: `ai-dlc knowledge check "$KNOWLEDGE_REPO"` from the PR branch, or wait for CI.
2. Mark a draft ready (`gh pr ready <number>`), then approve. You cannot approve a PR you opened.
3. Merge when the knowledge check is green. A change under `team/conventions/` also needs a code owner's approval.

After the merge, a numbering PR may give each new record its `DEC-`, `CONV-`, `ACT-` or `Q-` id. The wiki in
`{{wiki_space}}` is rendered from the records; never edit it there.
