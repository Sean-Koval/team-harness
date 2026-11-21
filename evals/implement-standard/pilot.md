# First work-default pilot

The final intake cue was observed on all seven relevant advice requests. A routine setup question stayed on the ordinary path. Routing scored **31/35** for the final candidate and **29/35** for the baseline. One run per case and arm gives a list of behaviors to investigate. It cannot establish a reliable lift or estimate cost savings.

## What changed between runs

| Arm | Work-default source and rendered digest | Where the agent saw the cue |
| --- | --- | --- |
| Baseline | Main source `2503d41`, rebuilt locally, `5cf673eb86e4fb7b4f37a4f87a83f1af8aa02fbd25709923159204e58d718f23` | Existing work guide, skill absent |
| First candidate | Intermediate local build, `3ef1020f9c6c811f123e3bd19cf3e049a01e9d878f9373e203891ac9be764c29` | “Before editing” in the planning step |
| Final candidate | Harness source `dbc1cdb`, `d518ddd71ff4bbafbf6ce697bbcdba39240a011241c96d45822f75f1fd57130a` | Ticket intake explicitly covers advice, implementation and review. The skill also explains how to keep ownership open when multiple causes fit. |

All arms used the real project installer on separate scratch directories. Each trial used a fresh gpt-6.2-sol session at medium reasoning effort on the same shared Linux host with the same shell access. Each agent followed the installed `.claude/CLAUDE.md` import and received the same fixture ticket within each case. Case instructions never named the skill. Sessions were instructed to read only the assigned fixture. The host did not enforce separate filesystem mounts. Claude Code hooks, live Jira, and hosted Hangar were outside these runs.

## Advisory results

The five criteria cover discovery, primary owner, evidence, calibration and verification. A scorer read the answers with opaque IDs and the case rubric, with harness labels and skill-read receipts withheld. Some answers cite the example inside the skill, so its use could occasionally be inferred. The routine setup question has its own pass/fail result.

| Case | Baseline | First cue | Final cue | What the final answer did |
| --- | ---: | ---: | ---: | --- |
| Shared exporter lacks a capability | 5 | 5 | 5 | Put schema support in the shared writer and column order in the team caller. |
| Toolbar bypasses the supported UI | 3 | 3 | 4 | Fixed the caller in the proposed plan and gave forbidden and allowed imports for a scoped check. It left enforcement optional and draft-specific. |
| New services inherit an old pin | 3 | 3 | 4 | Changed the source template in the proposed plan and specified old/new behavior checks. It omitted rollout to existing consumers. |
| PR skips a working local rule | 5 | 5 | 5 | Located the push-only condition on the PR job and separated this from unverified branch settings. |
| Incomplete keyboard-focus trace | 3 | 3 | 4 | Kept ownership open and identified the distinguishing trace. A separate known-good flow was missing from the proposed verification. |
| Concurrent retries create two rows | 5 | 5 | 5 | Put atomic uniqueness in shared storage and tested the reasoning against concurrent and distinct keys. |
| Routine setup summary | Pass | Pass | Pass | Returned the requested two setup bullets. |
| Ticket conflicts with a Privacy decision | 5 | 4 | 4 | Sent the conflict to its two owners first. The verification plan omitted an ordinary permitted export under the current rule. |
| **Routing total** | **29** | **28** | **31** | Maximum 35. |

In the first candidate, none of the seven relevant receipts listed reading the skill. This relies on the agents' read logs. In the final candidate, a file-open observer covered all eight sessions from before startup. It recorded opens on seven relevant cases and none on the routine case. A file-open event establishes discovery. The answer and its independent score establish how the agent used the guidance.

## A new feature built in both arms

Two further fresh sessions each implemented the same ticket to expose Archive Draft in a quick-actions menu. Both reused the existing confirmation component, added two tests and passed all three repository tests. An independent Node grader drove the exported mounting function, pressed Enter and Escape, checked which draft was removed and checked that focus returned to the list. The untouched fixture passed its original test and failed the independent grader on focus after Escape. Both agent implementations passed that grader. The candidate opened the skill during this task. This example demonstrates a working build in both arms. The additional skill produced no observed difference in the graded outcome. Keyboard events and focus targets here were simulated. The separate worked dialog example was also exercised in Chromium.

## Next evaluation

Repeat the paired trials in the pinned native Claude Code environment, including an actual review task. Use a fresh set of examples before tuning further. Check whether agents recommend appropriate cross-caller enforcement, account for existing consumers and supply positive controls. The evaluation instructions and fixtures are in [README.md](README.md). The source and extended trial record are in [PR 108](https://github.com/Sean-Koval/team-harness/pull/108). The native pilot is tracked in [KAN-597](https://seanmkoval.atlassian.net/browse/KAN-597).
