# Test whether a project standard reaches the next engineer

Use the [team guide](../../../docs/working-with-standards.md) for day-to-day implementation. These 64 synthetic tickets check three different outcomes. Did a fresh agent discover the skill in time? Did it identify the owning code, test, workflow or human decision? On an authorized build ticket, did it actually change and verify the repo?

The original 54 tickets cover UI and accessibility, shared-library adoption, MCP and bot contracts, storage, rollout, authorization, CI and harness discovery. Each includes 12 edits, three read-only decision requests and three ordinary questions. One edit per panel is intentionally routine. A separately reviewed panel adds ten harder cases with conflicting evidence, six edits and four decision requests. Across the two panels, 52 tickets are expected to need the skill. Keep the core and supplementary scores separate when comparing runs. Some scenarios use a simple executable model of a UI or CI rule.

## Run a ticket

Use Python 3, Node.js and a POSIX shell in a disposable development environment. From the root of Team Harness:

```sh
python evals/implement-standard/field/field.py list
trial_dir=$(mktemp -d)
python evals/implement-standard/field/field.py prepare A09 "$trial_dir/case"
```

Install the work-default build under evaluation in that project, following the [pilot install instructions](../README.md). Give the engineer only the checkout, the installed harness and the ticket. Keep these case files, which include expected decisions and checks, outside the engineer's environment. In a separate matched session, deliver the same skill explicitly and start from the same unedited fixture. Record model, runtime and harness digest. Give each case and condition a fresh session.

Once the engineer hands back an edit, run both the ordinary check and the private acceptance check in a disposable copy of the delivered project. The evaluator executes project code. Use the same isolated environment for both conditions.

```sh
python evals/implement-standard/field/field.py verify A09 "$trial_dir/case"
```

On read-only tickets, use the authored owner, acceptable behavior and forbidden actions to review the answer. Check the command record when a user asked the engineer to run something. On edit tickets, also inspect changed files, retained exceptions and whether the engineer ran the repo's ordinary check. A private check can pass even when a change adds an unnecessary approval or hardcodes the fixture.

## Read the result

| Observation | What to investigate |
| --- | --- |
| Skill absent from the installed workspace | Build, channel, installation and project scope. |
| Skill available but missed on a relevant ticket | Always-loaded project intake, routing or native discovery. Compare with routine tickets. |
| Skill read but the wrong owner chosen | The skill's decision rule and the evidence visible in that repo. |
| Correct owner named but no authorized edit made | The Build instruction, ticket authority and write permissions. |
| Code behaves correctly on delivery but the check stays green on a future violation | The repo test or lint boundary. Try one deliberate violation and one legitimate exception. |
| A local check fails correctly but the PR skips it | The job's path filter, actual check command and required status on the affected revision. |

Record natural timely access and correct actions separately. Include unexpected opens and unnecessary new requirements on routine work. Repeated green results in these small repos leave native discovery, noisy production tickets and branch protection to be tested on the actual deployment.

## Check the filing decision

This separate holdout contains 24 frozen synthetic requests. It checks whether a ticket filer adds the exact Jira label `standards-change` when the request calls for a shared standard. Export only the briefs and give them to the filer in a fresh session with the filing guidance. Keep the scorer and expected decisions outside that session. Ask the filer to return a JSON array with one entry per masked reference, for example `[{"ref":"HX-000","labels":["proposed","standards-change"]}]`. Extra fields such as a short reason are allowed.

```sh
python evals/implement-standard/field/filing.py export > /tmp/filing-briefs.json
python evals/implement-standard/field/filing.py score /tmp/filing-predictions.json
```

Save the predictions before scoring. The scorer rejects incomplete or mismatched submissions and reports counts for correctly marked briefs (TP), misses (FN), routine briefs marked (FP), and routine briefs left unmarked (TN). It lists ambiguous briefs separately for review. Inspect the misses and false positives when comparing filing guidance. This check measures the filing decision on these briefs. The field panel above measures skill discovery and implementation separately.
