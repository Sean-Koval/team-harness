---
name: org-process
description: Use before planning any work ticket, and whenever the company's flow is in question (which tickets a change needs, who approves, which gates come before a merge). Explains how this company runs work as tickets. This copy is the public placeholder; a company replaces it with its own flow skill.
---

# How this company runs work (placeholder)

> **Replace this file with your company's flow skill.** Drop it in as it is, keep `name: org-process`, and put any
> reference files it needs next to it in this directory. Then fill `../../org.yaml` with the same ticket types and
> gates, set `placeholder: false` there, and run `python scripts/sync_shared.py` (see `orgs/README.md`).
> Nothing below is a real company's process.

While this placeholder is installed, the company's flow is unknown. Follow the harness's guide and skills as they
are, file no approval ticket, and say in the PR that the org overlay is not applied.

## Ticket types

The kinds of ticket the flow uses, where each one lives and what it is for. For example: the work ticket in
`WORKPROJ`, and one approval ticket per gate in `SREPROJ` or `SECPROJ`.

## Approval tickets

For each approval ticket: when it is needed, what its summary and description must say, what it links (the PR, the
work ticket, the repository) and who files it.

## Gates before a merge

What must be approved, in what order, before a PR may merge, and which changes (paths, labels) bring in which gate.

## Who approves

Which team or role reviews each approval ticket, how long it usually takes, and where to ask when it stalls.

## Review requests

Where the team asks for review, and what the message says. Agents draft it; a person posts it.

## When this file and org.yaml disagree

This skill wins. Follow it, and say in the PR which row of `org.yaml` differed, so a person can fix the overlay.
