# Try Work Copilot, AI-DLC and Team Harness together

Start with one fictional ticket on your machine. Work Copilot keeps the cited source, AI-DLC validates the work record and spec link, and Team Harness delivers the standards guidance. The product repo owns the test.

## 1. Run the rehearsal

Use Git and [uv](https://docs.astral.sh/uv/getting-started/installation/). The first run needs network access to fetch the two pinned tools and their dependencies. uv can obtain Python 3.12. From a terminal, run:

```sh
git clone https://github.com/Sean-Koval/team-harness.git
cd team-harness
git switch KAN-607-three-tool-pilot
uv run --python 3.12 evals/three-tool-pilot/smoke.py
```

The branch command selects this revision while it is under review. After merge you can run the same script from a clean checkout containing it. The Team Harness version comes from that checkout’s candidate channel.

| What to look for | What it proves |
| --- | --- |
| A marked issue receives the installed skill and matching hash. The same issue with its label removed omits it. | The launcher handles a known label. Natural skill discovery needs a separate agent run. |
| Work Copilot recovers the source after restart. AI-DLC validates one exported Source through its CLI and MCP. | The tools exchange the same evidence locally. |
| AI-DLC rejects the missing spec reference. The product test catches changed output and accepts explicit verbatim mode. | The record check and product check each catch a different failure. |
| `PASS Temporary fixtures removed. This run covers local commands and stdio MCP.` | The entire rehearsal completed. A failure before this point names the stage to investigate. |

The product verifier is `python -m unittest -v test_banner` from the [banner fixture](fixture/). CI runs the three-tool rehearsal on the generated candidate.

The runner creates its own data in a disposable checkout. Your uv cache retains dependencies. The procedure has been exercised on Linux. Company logins, model behavior, protected CI and native Mac or Windows onboarding need their own trials.

## 2. Try one real repository

For a personal trial, use a disposable branch of a personal repo, your own knowledge repo, a new private Work Copilot directory and personal accounts. Keep the product verifier in that repo. Use the public harness with fictional inputs to try the company workflow. For company work, the maintainer supplies the approved private candidate and work-only locations. [Setup and cleanup](connect.md)

## 3. Review the change and hand it off

Give one pair a shared UI promise such as keyboard focus after Cancel. Give the other a published MCP response and an allowed draft variation. Each pair works one existing issue.

1. **Spec.** Retrieve the governing source through Work Copilot. Link the Decision and the spec in the AI-DLC work record. If “return to where I was” could mean two different focus targets, name a case that distinguishes them and who can decide.
2. **Build.** Trace a real caller. Put the behavior in the owning component or library. Add a scoped check where a caller can bypass it. CI runs the same command the engineer used locally.
3. **Code and docs review.** On a scratch branch, break the promise and observe the normal PR job fail for that reason. Restore the change and try the allowed case. Give the reviewer the revision, command, expected and actual result. For docs, run the published command cold, remove sentences without a fact or reader action, and retain compatibility and recovery details.
4. **Handoff.** Swap repos. Give the next engineer a new caller without naming the skill. Record the diff, real PR check, manual interventions and minutes on the ticket. Keep existing architecture, SRE, database and merge approvals. Sample naturally relevant unmarked work and routine tickets alongside labelled work. [Guide to choosing the owning layer](../../docs/working-with-standards.md)
