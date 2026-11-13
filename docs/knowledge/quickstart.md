# Quickstart: your first record in 15 minutes

You will turn a sample meeting into three records, review them and merge them. The records land in a practice
project of your own, `projects/practice-<your login>/`, so they never mix with the team's decisions.

The Windows commands are for PowerShell and are **untested on Windows**. Steps 1 to 3 are what the one-command
install (KAN-433) will do for you; once it lands, run it and `ai-dlc doctor`, then start at step 4.

## Before you start

You need git, the GitHub CLI signed in (`gh auth status`), Python 3.10 or later with PyYAML, and Claude Code. Install
ai-dlc as `{{ai_dlc_install}}` says. On Windows, ai-dlc is not supported yet (ai-dlc#172).

Clone three repositories side by side: `{{harness_repo}}`, the knowledge repository `{{knowledge_repo}}`, and a work
repository you use with Claude Code. The examples use `~/src`.

## 1. Install the harness into your work repository

The installer copies the skills and hooks into the work repository's `.claude/` and changes nothing else. It
previews first; `--apply` writes and `--check` confirms. `--uninstall` removes exactly what it wrote.

macOS:

```sh
cd ~/src/svc
python3 ~/src/team-harness/scripts/install_local.py ~/src/team-harness/harnesses/work-default \
  --scope project --target . --channel candidate
python3 ~/src/team-harness/scripts/install_local.py ~/src/team-harness/harnesses/work-default \
  --scope project --target . --channel candidate --apply
python3 ~/src/team-harness/scripts/install_local.py ~/src/team-harness/harnesses/work-default \
  --scope project --target . --check
```

Windows (untested):

```powershell
cd $HOME\src\svc
$th = "$HOME\src\team-harness"
py -3 "$th\scripts\install_local.py" "$th\harnesses\work-default" --scope project --target . --channel candidate
py -3 "$th\scripts\install_local.py" "$th\harnesses\work-default" --scope project --target . --channel candidate --apply
py -3 "$th\scripts\install_local.py" "$th\harnesses\work-default" --scope project --target . --check
```

`--check` prints `clean`. Use `--channel candidate` because `stable` (r3) does not have `extract-records` yet. Drop
the flag once a promotion moves `stable` past r6.

**Windows:** the hooks run natively on Windows (#16). The installer writes `py -3` into `.claude/settings.local.json` and its
`--check` starts each hook once, in Git Bash or PowerShell as Claude Code does (#40). A hook that cannot start fails the
check with `its guard is OFF` (#33). Step 2's test is still worth doing once.

## 2. Point your shell at the knowledge repository

Set `KNOWLEDGE_REPO` in the shell you start Claude Code from, then check the clone.

macOS:

```sh
export KNOWLEDGE_REPO=~/src/knowledge
ai-dlc knowledge records --help
ai-dlc knowledge check "$KNOWLEDGE_REPO"
```

Windows (untested):

```powershell
$env:KNOWLEDGE_REPO = "$HOME\src\knowledge"
ai-dlc knowledge records --help
ai-dlc knowledge check $env:KNOWLEDGE_REPO
```

The check ends `0 failures`. Then test the guard: in Claude Code, in a scratch repository on `main`, ask it to run
`git commit --allow-empty -m test`. The hook refuses with `blocked by the work-system hook`.

## 3. Put the sample meeting in the inbox

`sample/practice-sync.md` is a short fictional meeting. Copy it into the inbox with your GitHub login in place of
`YOUR-LOGIN`. Your login makes the meeting yours, so nobody else's practice run counts as a duplicate.

macOS:

```sh
ME=$(gh api user --jq .login)
sed "s/YOUR-LOGIN/$ME/g" ~/src/team-harness/docs/knowledge/sample/practice-sync.md \
  > "$KNOWLEDGE_REPO/inbox/practice-sync-$ME.md"
```

Windows (untested):

```powershell
$me = gh api user --jq .login
$text = (Get-Content "$HOME\src\team-harness\docs\knowledge\sample\practice-sync.md" -Raw) -replace 'YOUR-LOGIN', $me
[IO.File]::WriteAllText("$env:KNOWLEDGE_REPO\inbox\practice-sync-$me.md", ($text -replace "`r`n", "`n"))
```

`WriteAllText` writes UTF-8 without a byte-order mark, which the record parser needs. Leave the file uncommitted:
the PR carries its processed copy.

## 4. Extract the records

Start Claude Code in your work repository, from the shell where you set `KNOWLEDGE_REPO`, and ask:

```text
Run extract-records on $KNOWLEDGE_REPO/inbox/practice-sync-<your login>.md.
Use --provider git. Its scope is project practice-<your login>.
End every record's id with -<your login>.
```

The last line matters: record ids are unique across the whole repository, and every teammate's practice meeting
gives the same records.

The skill reads the meeting, writes the records into a scratch copy, runs `ai-dlc knowledge check` and opens a
**draft** PR. Allow the writes it asks for in the scratch directory. It reports the PR link.

If it stops because it cannot find ai-dlc's record templates, tell it to print them:
`ai-dlc knowledge records template --list` names the types, and `ai-dlc knowledge records template decision` prints
one. If ai-dlc does not know `template`, update it.

## 5. Review the PR

The PR should hold four files under `projects/practice-<your login>/`:

| File | Type | Status | Owner | Evidence starts |
| --- | --- | --- | --- | --- |
| `sources/practice-sync-<login>.md` | source | processed | you | the whole meeting |
| `decisions/…` | decision | accepted | you | `[00:00:45] <login>: Decided:` |
| `actions/…` | action | open, due 2026-11-20 | you | `[00:01:40]` |
| `questions/…` | question | open | lead-example | `[00:02:10]` |

The line at `[00:01:05]` restates the decision, so it gives no record. Review the PR as [review.md](review.md) says.
Fix or drop anything that differs from this table, and add each surprise to your onboarding notes.

## 6. Merge, then find your record

Mark the PR ready (`gh pr ready <number>`), ask a teammate to approve it, and merge it once the knowledge check is
green. You cannot approve your own PR. After the merge, a numbering PR may give each record its `DEC-`, `ACT-` or
`Q-` id.

```sh
git -C "$KNOWLEDGE_REPO" pull
ai-dlc knowledge records search --provider git --type decision --text "practice-$ME"
```

On Windows, use `$env:KNOWLEDGE_REPO` and `$me`. Then delete the inbox copy from step 3. You are done; read
[capture.md](capture.md) next.
