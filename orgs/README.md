# Org overlays

An org overlay is a company's own flow, kept out of the shared work-system files: its ticket types, the approval
tickets and gates a PR needs before it merges, and where review is asked for. `scripts/sync_shared.py` renders it
into a work harness, and `release-approvals` runs the gates it declares.

```text
orgs/<org>/
  org.yaml                      schema team-harness.org/v2 (v1 still loads): params, reviewers, stages,
                                ticket types, gates, review request
  skills/org-process/SKILL.md   the company's own flow skill, copied verbatim (name: org-process)
  skills/org-process/...        any reference files it needs
```

`orgs/example-co/` is the public example. Every value in it is a placeholder (`COMPANY-SITE`, `COMPANY-ORG`,
`WORKPROJ`, `SECPROJ`, `ESSPROJ`, `ARCHPROJ`, `CHGPROJ`) and it says `placeholder: true`, so agents on it file no
approval ticket.

## What v2 adds (KAN-373)

Set `schema: team-harness.org/v2` to use these. A v1 overlay keeps working, and refuses the v2 keys with a hint.

- `reviewers`: review teams by id, each with a `name` and an optional `github_team` (`org/slug`).
- `stages`: named steps in order. A stage with `branches` is a merge into one of them; a stage without is a later
  step, such as a release, that the PR check doesn't hold the merge for.
- On a gate, `approved_on: work` means the approvers approve the work ticket itself, so nothing is filed. Write
  `approved_on`, never `on`: YAML reads a bare `on` as true. The default is `ticket`.
- `approvers` names a reviewer; `github_review: true` also needs an approving review of the PR's latest commit
  from a member of that reviewer's GitHub team.
- `scope: repo` makes a gate one ticket per repository, reused across PRs. `stage` ties a gate to a stage.
- `approved_field: {field, values}` passes on a Jira field's value instead of, or as well as, a status.
- `needs_approval: false` records a ticket for the audit trail; nothing waits on its approval.
- `when` also takes `issue_types` and `projects`, matched against the work ticket.

The PR check (`actions/work-system-pr`) reads the same file. When it can't read the data a gate needs, the gate
applies, and its approval counts as unverified, which fails the check.

## Add your company's org

Do this in your company's private fork, never in the public repository.

1. Copy `orgs/example-co/` to `orgs/<your-org>/`, and set `name: <your-org>` in its `org.yaml`.
2. Replace `skills/org-process/SKILL.md` with your company's flow skill. Keep `name: org-process`.
3. Fill `org.yaml`: the tracker and knowledge-base `params`, every `ticket_types` entry, the `gates` in order, and
   the `review_request` room and template. Then set `placeholder: false`. `params` may set only `tracker` and the
   `kb_*` keys; the merge rule, the wall and the approval steps stay the harness profile's.
4. In `shared/work-system/targets.yaml`, change the harness's line to `org: orgs/<your-org>`.
5. Commit only your org files and that line. The copies, the lock and `candidate` are built on main after merge
   (KAN-481). To test locally first:

   ```sh
   python scripts/build_generated.py     # sync, relock, render, candidate
   python scripts/build_generated.py --restore   # before you commit
   ```

Org skills are copied verbatim, never rendered, so a company document may hold `{{ }}` as it likes. Each skill
needs frontmatter `name:` equal to its directory. `sync_shared.py` deletes a harness skill that nothing produces any
more, so a removed or renamed org skill does not linger. A harness's own skills are listed in `own_skills:` in
`targets.yaml`.

`--check` fails on an unknown key, a param an org may not set, or a duplicate gate id or PR line. It fails on a gate
whose ticket type is unknown or not an approval, and on a bad `when` or `filed_by`. A summary or template that is
malformed, has doubled braces or names an unknown field fails too. So does a summary with both `{work_key}` and
`{pr_title}`: the PR title already starts with the key.

It also fails when a copy drifted or is left over, or when `suite-default` names an org: personal and company work
never share a harness.

If `org-process` and `org.yaml` disagree, agents follow `org-process` and say in the PR which row differed.
