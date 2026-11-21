---
name: implement-standard
harnesses: [work-default]
description: Use when asked where a change belongs, how to verify or enforce a shared behavior, or how to apply a design or architecture standard. Covers advice, implementation and review.
---

# Implement a standard

Start with the requested outcome, design handoff, architecture decision, or review feedback. Read the source material, repo instructions, and existing implementations. Record where the rule came from, what it applies to, and a concrete example outside the rule if scope could be ambiguous. State assumptions that affect the work. Use the product repo's conventions and delivery workflow.

## Establish the applicable standard

Read the ticket and repository guidance to identify the standard, its source, and the callers or behavior it covers.
Compare it with an existing implementation before choosing what to change. For routine work with no relevant standard
to evaluate, continue with the usual workflow.

If the rule or its scope is still missing, ambiguous, or contradictory after inspection, record the sources, the
specific question, and the affected scope. Use `decision-ticket` where available or follow the repository's decision
process. Pause the affected work until the decision is resolved.

## Choose the mode from the request

| Mode | Deliverable |
| --- | --- |
| Plan | Propose the owning code, rollout or callers to update, and the smallest checks that would establish the promise. Label proposed checks as planned and record any decisions still needed. |
| Build | Implement the supported path and update in-scope callers. Run the applicable checks and record observed results and anything still pending. |
| Review | Inspect the change and its evidence against the rule. Lead with concrete findings ordered by impact, with file or evidence links, the consequence, and the smallest repair. State any gaps in verification. |

Carry the result in the existing issue, plan, or PR. If there is no suitable form, run `python path/to/implement-standard/scripts/worksheet.py plan` using the path to this skill, then paste the Markdown where the team records the work. Use `build` or `review` for the other modes. The tool prints to stdout and works from any repo.

## Work from the top down

**Inspect before prescribing.** Compare one affected caller with the supported example. Inspect the actual dependency version, source or generated template, and relevant check or CI run as needed. Treat a trace or screenshot as a lead. A fresh feature can start from its agreed acceptance example. If multiple causes fit the evidence, lead with “ownership is still open” and the smallest inspection that distinguishes them. Name the competing owners and the observation that would select each. A missing trace calls for investigation. A conflict over the desired behavior goes through the decision process above.

**Choose one primary owner.** Walk the four questions below in order. An existing layer can already satisfy the promise. Change the earliest *applicable* owner, then add only the lower-layer checks or guidance needed to demonstrate and sustain it. Report which layers you would change, reuse, or skip and why. Several symptoms can share one fix.

1. **Code and architecture.** Write the promise in one observable sentence and give a counterexample that would violate it. Find the component, API, type, or module that should own it. Reuse or improve the supported path and identify the callers or examples that should adopt it. Point to existing enforcement when the repo already provides it.
2. **Executable checks.** Identify the mistake still possible through normal repo work and the smallest check that can detect it. Use dependency rules or a linter for source structure, types for invalid combinations, and tests for outputs or state. Reuse an existing rule before writing a custom one. For a new rule, exercise a passing case and a deliberately failing case in a fixture or scratch copy. The diagnostic should point to the supported path. Keep the repaired version.
3. **Behavioral evidence.** Exercise the ordinary user or caller entry point. Choose evidence that distinguishes success from a plausible false pass. For a UI interaction, operate the control with a keyboard and check focus or state. For an architecture rule, check the boundary where it matters to a real caller. Use property tests or model checking when combinations of states justify them. Capture the smallest useful output.
4. **Guidance.** Capture rationale, exceptions, and remaining judgment in the existing guide. Link the working example. When a layer adds no coverage for the promise, state why and move on. For a subjective design decision, name the reviewer and the question.

## Break ties using what you observe

| Observation | Primary recommendation |
| --- | --- |
| Correct use of the current shared API cannot deliver the required behavior for its supported consumers. | Change the shared library or component and test its public behavior. If the capability already ships, check whether consumers need an upgrade. If just one caller passes the wrong data, repair that caller. |
| The supported path works, yet callers can bypass it through a forbidden source pattern. | Consider narrowing module exports first. If legitimate internal callers still need the primitive, use a scoped dependency or lint rule. Name the replacement in the error. Test one forbidden caller and one allowed internal caller. |
| Source looks valid, yet behavior is wrong for a particular input or sequence. | Repair the behavior at the owning boundary and add a regression or property test through the normal entry point. Include an input on which the good and bad implementations differ. |
| A safe check rejects the bad change locally, yet the PR is green. | Inspect the exact revision, command, trigger, paths and required status. Fix CI wiring or branch settings when the check is missing or nonblocking. A local environment mismatch belongs in setup. |
| Fresh repos inherit the mistake, or only fresh agent sessions miss the supported path. | Generate a clean project to test the template. If the template is correct, inspect the startup instructions actually loaded by the agent. Fix a repo pointer for a local convention or Team Harness for a shared discovery problem. |
| The decision needs design judgment or human authorization. | Identify the owner and decision. For approvals, use the existing workflow gate. For a one-off incident, record the local resolution if that suffices. |

**Lead the reply with a recommendation.** Tell the engineer: “I recommend changing [owner and location] because [observed evidence]. [Nearest alternative] would apply if [different evidence]. I would prove it with [specific bad and good case].” Mark uninspected facts as unknown. When the user asks where a fix belongs, return advice in Plan mode. In Build mode, carry out scoped changes and report actual results.

Use the repo's verification command locally and follow its CI workflow. Name the relevant CI job and link its evidence when available. Record observed local results, observed hosted CI results, and proposed merge requirements in their respective status. If CI integration is outside scope, record the missing check and who owns it if known.

See the [worked confirmation dialog](examples/dialog/README.md) for a shared primitive, an actionable lint rule, and a browser check that exercises the failure case.
