# Org overlays

An org overlay is a company's own flow, kept out of the shared work-system files: its ticket types, the approval
tickets and gates a PR needs before it merges, and where review is asked for. `scripts/sync_shared.py` renders it
into a work harness, and `release-approvals` runs the gates it declares.

```text
orgs/<org>/
  org.yaml                      schema team-harness.org/v1: params, ticket types, gates, review request
  skills/org-process/SKILL.md   the company's own flow skill, copied verbatim (name: org-process)
  skills/org-process/...        any reference files it needs
```

`orgs/example-co/` is the public example. Every value in it is a placeholder (`COMPANY-SITE`, `WORKPROJ`,
`SREPROJ`, `SECPROJ`) and it says `placeholder: true`, so agents on it file no approval ticket.

## Add your company's org

Do this in your company's private fork, never in the public repository.

1. Copy `orgs/example-co/` to `orgs/<your-org>/`, and set `name: <your-org>` in its `org.yaml`.
2. Replace `skills/org-process/SKILL.md` with your company's flow skill. Keep `name: org-process`.
3. Fill `org.yaml`: the tracker and knowledge-base `params`, every `ticket_types` entry, the `gates` in order, and
   the `review_request` room and template. Then set `placeholder: false`. `params` may set only `tracker` and the
   `kb_*` keys; the merge rule, the wall and the approval steps stay the harness profile's.
4. In `shared/work-system/targets.yaml`, change the harness's line to `org: orgs/<your-org>`.
5. Render and re-pin:

   ```sh
   python scripts/sync_shared.py
   python scripts/relock.py harnesses/work-default --write
   python scripts/render_envs.py harnesses/work-default
   python scripts/sync_shared.py --check
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
