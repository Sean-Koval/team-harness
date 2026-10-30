Add mutation scoring of behavior suites: remove one harness component at a time and check whether a grader or a
behavior spec notices. New module `flightdeck.specs.mutate` and a `flightdeck mutate plan|run|score` command group.

- `mutate.OPS`: the operators `drop-skill`, `drop-instruction-line`, `approvals`, `noop`, and `drop-hook` and
  `widen-egress`, which are not generated (they need harness locks or a per-experiment egress); asking `plan` for
  one raises `ValueError` naming it.
- `mutate.plan(base_variant, ops, seen_skills=None, cap=None) -> dict`: mutants keyed `mutant-<op>-<component>`
  (component slugged, e.g. `mutant-drop-skill-skill-tdd`), each `{op, component, variant, equivalent}`. Components:
  `skill:<name>` (each skill dropped from `skills`; with no `skills`, `skills_remove: [name]` for each seen skill),
  `instructions_append:<i>` / `instructions:<i>` (each block, split at markdown headings, else per line, removed),
  `approvals:auto` (when the base is `deny-risky`), and `none` for the no-op control. A skill never seen in traces
  and the no-op are `equivalent`. `cap` limits the count.
- `mutate plan SUITE --harness BASE --out FILE [--ops a,b] [--max 12] [--n 2] [--data PLANE]`: writes a loadable
  suite file whose variants are the base and the non-equivalent mutants, with `base:`, `n:` and `mutants:` keys;
  prints each skipped operator as `not generated\t<op>`.
- `mutate run PLAN [--max-usd 40] [--dry-run]`: through the experiment cost gate; prints `projection: $<x>` first
  and refuses a plan over the cap (exit 1, `over --max-usd`).
- `mutate score PLAN RUN_SET --specs ... --data PLANE [--bound 0.9] [--out FILE]`: a mutant is killed when resolved
  differs from the base (paired task-bootstrap 95% interval excludes 0; reason `resolved <+/-N> pp`) or a spec that
  held on the base (pass^k >= bound) falls below it (reason `spec <id>: pass^k 1.00 -> 0.00`). The markdown has a
  table `| <mutant> | \`<component>\` | killed / survived / equivalent / not run | <reason> |` (not run: `no trials in
  the run set`), a line `**K/N killed (P%, 95% Wilson ...` with `E equivalent and M not run (not counted)`, and each
  survivor with a suggested spec, e.g. `- \`skill:review\`: \`eventually: {tool: {skill: review}}\``.

Also, `stats compare` must not raise when no trial in an arm has a known cost. Document it under `docs/`.
