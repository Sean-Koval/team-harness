# regression-v0

Twenty tasks mined from merged pull requests by a written rule, so the flightdeck#20 A/B (`../../decision.yaml`,
KAN-31) can run before regression-v1 (flightdeck#12, KAN-88) has labelled failures to mine. Built by KAN-222.

Each task is a flightdeck task directory (flightdeck `docs/tasks.md`, Harbor format): the repository at the merged
fix's parent commit, an instruction that states the problem, and the PR's own test file as the hidden test.

## Where it lives

flightdeck's ADR 0002 puts regression tasks in a private data repository. None exists yet, so the suite is here,
beside `decision.yaml`. **Move it to the private data repo when one is created**, and point `../../suite.yaml` at
that checkout. The source repositories are public, so nothing here is secret today. But it is readable by anyone,
trial sandboxes included (see [Isolation](#isolation)).

## The selection rule

The rule is [SELECTION.md](SELECTION.md), committed before any pull request was listed. In short:

- Every pull request merged into `main` before 2026-10-29 in flightdeck, team-harness and ai-dlc, plus hangar pull
  requests whose fix is one module (one `.py` under `src/hangar/`).
- It changes or adds `tests/**/test_*.py`. Its fix (files outside `tests/` and `docs/`, not `*.md`) is 1 to N files
  of code.
- Excluded: docs-only changes, dependency bumps, and hidden tests too big for hangar's one grader.
- **Fail-to-pass**: the PR's changed test files fail on the parent commit and pass on the merge commit, twice.
- The model is `claude-opus-5-5` (knowledge cutoff June 2026, released 2026-09-21). Every repository was created
  after 2026-10-10, so every task's `mined_after` (its merge date) is after the cutoff.

### What the rule produced

297 pull requests were screened: flightdeck 42, hangar 251, team-harness 4. ai-dlc is missing: this session's
GitHub REST access to it was refused, so its pull requests could not be listed.

| Step | Left |
| --- | --- |
| Changes a test, fix of 1 to 3 code files (hangar: one module) | 17 (flightdeck 3, hangar 14) |
| Fail-to-pass, at N = 3 | 17 |
| At most 3 grader files per task | 15 |
| Widened to N = 5 (SELECTION.md's first fallback): flightdeck #88, #65, #62, #53 | 18 (#65's test passes on its base) |
| Deviation: the per-task file cap replaced by hangar's real limit | **20** |

The window couldn't be extended back: it already starts at each repository's first pull request. So the second
fallback was spent, at 18 tasks.

**Deviation, recorded after looking at outcomes.** The rule's cap of 3 grader files per task was a proxy for
hangar's limit of 64 files for all tasks. Two hangar pull requests (#364, #232) need 4 files (`test.sh`, two test
files, `conftest.py`). The cap was replaced by the limit itself: the suite uses 54 of 64 files and 519 KB of 1 MB.
Fail-to-pass was never relaxed. hangar's one-module restriction was not widened.

## The tasks

| Task | Pull request | Merged | Base | Hidden tests |
| --- | --- | --- | --- | --- |
| `hangar-384-pin-check-ended-job` | [hangar#384](https://github.com/Sean-Koval/hangar/pull/384) | 2026-10-27 | `d1f48fb87751` | test_pinsets.py + conftest.py |
| `hangar-364-repo-set-naming-flags` | [hangar#364](https://github.com/Sean-Koval/hangar/pull/364) | 2026-10-23 | `c6aad386ab02` | test_frontdoor.py, test_editorial.py + conftest.py |
| `hangar-359-inbox-redaction` | [hangar#359](https://github.com/Sean-Koval/hangar/pull/359) | 2026-10-23 | `6105e726b9ff` | test_inbox.py + conftest.py |
| `hangar-358-ghcr-docker-login` | [hangar#358](https://github.com/Sean-Koval/hangar/pull/358) | 2026-10-23 | `01c136cecc62` | test_images.py + conftest.py |
| `flightdeck-88-release-check` | [flightdeck#88](https://github.com/Sean-Koval/flightdeck/pull/88) | 2026-10-27 | `64d83491e3ea` | test_release.py |
| `flightdeck-82-tail-numbers` | [flightdeck#82](https://github.com/Sean-Koval/flightdeck/pull/82) | 2026-10-21 | `c005c619b5d6` | test_tails.py, test_report.py |
| `flightdeck-64-compactor-data-bucket` | [flightdeck#64](https://github.com/Sean-Koval/flightdeck/pull/64) | 2026-10-19 | `ba5d1799fc94` | test_deploy.py |
| `flightdeck-62-docs-reference` | [flightdeck#62](https://github.com/Sean-Koval/flightdeck/pull/62) | 2026-10-19 | `6a79ebc1f368` | test_docs_reference.py |
| `hangar-280-thaw-subdirectory` | [hangar#280](https://github.com/Sean-Koval/hangar/pull/280) | 2026-10-19 | `abb506f0d760` | test_harness_thaw.py + conftest.py |
| `hangar-298-own-agent-commands` | [hangar#298](https://github.com/Sean-Koval/hangar/pull/298) | 2026-10-18 | `c02d4414aa6d` | test_driver.py + conftest.py |
| `flightdeck-58-airframe-theme-v2` | [flightdeck#58](https://github.com/Sean-Koval/flightdeck/pull/58) | 2026-10-17 | `f619b513ee7b` | test_airframe.py |
| `flightdeck-53-mutation-scoring` | [flightdeck#53](https://github.com/Sean-Koval/flightdeck/pull/53) | 2026-10-17 | `062583b8bb51` | test_mutate.py |
| `hangar-247-posture-fresh-laptop` | [hangar#247](https://github.com/Sean-Koval/hangar/pull/247) | 2026-10-17 | `266280580d0c` | test_posture.py + conftest.py |
| `hangar-232-a2a-output-schema` | [hangar#232](https://github.com/Sean-Koval/hangar/pull/232) | 2026-10-17 | `1a5084b9612e` | test_a2a.py, test_frontdoor.py + conftest.py |
| `hangar-208-governance-contract` | [hangar#208](https://github.com/Sean-Koval/hangar/pull/208) | 2026-10-17 | `2e5007d66717` | test_governance.py + conftest.py |
| `hangar-204-grade-anti-forgery` | [hangar#204](https://github.com/Sean-Koval/hangar/pull/204) | 2026-10-16 | `364243f344a0` | test_interfaces.py + conftest.py |
| `hangar-38-failure-comment` | [hangar#38](https://github.com/Sean-Koval/hangar/pull/38) | 2026-10-13 | `ebbeceabe7db` | test_jobs.py + conftest.py |
| `hangar-27-pack-list` | [hangar#27](https://github.com/Sean-Koval/hangar/pull/27) | 2026-10-12 | `760c6ab6bd70` | test_cli_json.py |
| `hangar-14-remote-tokens` | [hangar#14](https://github.com/Sean-Koval/hangar/pull/14) | 2026-10-12 | `3be08f686f47` | test_cli_tokens.py |
| `hangar-13-json-output` | [hangar#13](https://github.com/Sean-Koval/hangar/pull/13) | 2026-10-12 | `d99f91a1a18b` | test_cli_json.py |

Six are flightdeck tasks and fourteen are hangar tasks; team-harness contributed none. hangar #204's two other new
test files fail on the merge commit without root and Docker, so only `test_interfaces.py` is hidden there.

Three tasks are close to a full feature behind a large hidden suite: #208 (116 tests), #204 and flightdeck #53.
Expect them to resolve rarely in either arm. They still pair, and they still count for cost, the primary metric.

## The bias: agent-written pull requests

**All 20 pull requests were written by coding agents. 17 of them by `claude-opus-5-5` itself**, the model both arms
run (a `Co-Authored-By: Claude Opus 5.5` trailer and a Claude Code session link). Two are by Claude Sonnet 5.5
(#13, #14: trailer and `agent/` branch). One (#27) has no trailer but an `agent/pack-test-agy` branch, a hangar
Antigravity job.

So the suite measures work the model under test already finished once, in its own repositories, under a different
harness. Absolute resolved rates will read high for the operator's workflow and say little about human-written work.
The paired comparison of the two arms is less affected, since both arms share the bias. The ADR for KAN-31 should
cite these counts.

## Power

From flightdeck's `stats.core.simulate_power` (task base rates from Beta(1.2, 1.2), one-sided z test at α = 0.025):

| Tasks × trials | Power at 20 pp | 24 pp | 25 pp | 30 pp | Detectable at 80% |
| --- | --- | --- | --- | --- | --- |
| 20 × 3 | 0.67 | 0.82 | 0.85 | 0.94 | **about 24 pp** (`mde`: 25 pp in 5 pp steps) |
| 20 × 2 | 0.51 | 0.66 | 0.68 | 0.82 | about 30 pp |

That matches KAN-223. Tasks that resolve in neither arm carry no signal, so the real figure is worse than this.
Resolved is a guardrail here; cost is the primary.

## The grader

Every task runs `bash tests/test.sh`, one grader command for the experiment, as hangar needs. The script is
flightdeck's template, changed to run a repository's own tests:

- It copies the agent's tree, then replaces every `conftest.py` under `tests/` with the hidden copy's. It puts the
  hidden test files over the tree's own copies.
- It runs `python3 -I -m pytest -c /dev/null --confcutdir tests/`, with `src/` first on the path. So none of the
  tree's pytest settings, `sitecustomize.py` or other `conftest.py` load.
- The rest of `tests/` (fixtures, helper modules) comes from the agent's tree. A trial that edits those is visible in
  hangar's `touched_tests`; hangar records the grade as `trust: low` either way.

Each task's `solution/reference.patch` is the merged change without its hidden files and binary files, for
hangar's base-must-fail check.

## Isolation

GitHub access is scoped per repository for credentials, but this repository is public. Two leaks follow:

1. **team-harness is readable from trial sandboxes.** `team-default` and `team-default-candidate` set no `egress`,
   so they run in `HANGAR_EGRESS_DEFAULT`, which defaults to `open`. A trial can fetch this directory, hidden tests
   and reference patches included, from `raw.githubusercontent.com` without any token.
2. **The fix is in the task repository's own history.** A trial's clone comes from the gateway with a fetch grant,
   so `origin/main` (and the PR on github.com) hold the merged fix.

Before trial 1, run both arms with egress `allowlist` without the `github` preset, or `none`. That blocks the first
leak. For the second, hangar should give experiment trials a clone without refs past `base_sha`. flightdeck #58
needs agent-factory's `theme-v2` files; it is unsolvable without that host.

## Before the run

- **The grader needs each repository's dependencies.** hangar's grader has no network. The image the arms' grader
  sandboxes run must have flightdeck's and hangar's locked dependencies and pytest installed. Each
  `environment/Dockerfile` shows how, for the local runner. Without them every grade is 0, and the reference check
  marks every task invalid.
- `min_tasks: 20` in `decision.yaml` equals the suite's size. One task excluded in either arm makes the verdict
  "No decision: underpowered".
- With no cost history, `flightdeck experiment run ../../suite.yaml --dry-run` projects $360 at an assumed $3 a
  trial, over `budget_usd: 300`. KAN-223's ~$2 a trial would be $240.

## Checking it

```sh
flightdeck task check flightdeck/suites/regression-v0/tasks/*/   # 20 ok
python -m pytest -q tests/test_regression_v0.py                  # count, limits, decision.yaml names it
```

Fail-to-pass was checked on 2026-10-29 for every task: `test.sh` on the base fails and on the base plus
`solution/reference.patch` passes, twice. No trial was run.
