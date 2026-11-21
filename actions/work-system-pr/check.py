#!/usr/bin/env python3
"""The work-system PR check: every pull request names its ticket, says where its docs went, and (optionally) points
at a ticket that is open, carries an execution label and is not waiting on a decision.

Every surface (hangar jobs, local Claude Code or Codex, cloud sessions, a person in the browser) ends in a pull request,
so this is the one place the rules hold for all of them. The session hook (shared/work-system) only catches them
earlier. Rules:

1. The title starts with a ticket key (`KAN-315: ...`).
2. The body has `<tracker line>: <KEY>` (default `Jira: KAN-315`) for the same key.
3. The body has a non-empty `Docs:` line; `none needed` must give a reason.
4. If the body says `Decision: <KEY>`, the PR adds or changes a file under the ADR directory that mentions that key.
5. The branch should contain the key (a warning only: cloud sessions are assigned branch names).
6. With tracker credentials: the ticket exists, is not finished (Done, Wont Do), carries an execution label (`exec:`,
   or the older `lane:`), is a work item (not an Epic or a Decision, nor one labelled `type:decision`), and no open
   Decision blocks it. The ticket is read through tracker.py's provider (`tracker-provider`, default jira-cloud) as a
   normalised issue, so this file names no tracker's fields (KAN-437).
7. With an org file (`org-file`, schema team-harness.org/v1 or v2), read from the PR's base commit so a PR can't
   loosen its own gates: every merge gate whose `when` matches the PR (always, its changed paths, or the labels on the PR or its
   work ticket) needs a `<pr_line>: <KEY>` line naming a ticket in the gate ticket type's project (`pending` or a
   missing line fails, so merge waits on the approval tickets). With tracker credentials, each gate ticket, read through
   the same provider as a normalised gate ticket (KAN-538), must exist, be
   in that project, have the ticket type's issue type, carry the links the gate names (`work`: an issue link to the
   PR's work ticket; `pr`: a remote link to the PR or its URL in the description; `repo`: the repository's URL, or a
   link into it, in a remote link or the description) and, when the gate sets `approved_statuses`, be in one of them.
   The check fails closed: a gate with `approved_statuses` or `links` whose ticket can't be read (no credentials, the
   tracker down, an SSO page instead of JSON) fails, and so does the work ticket when tracker credentials are set but
   the tracker can't be read, unless `allow-unverified` is set. An org file marked `placeholder: true` is not enforced (a warning says
   so). A v2 org (KAN-373) adds: gates held only at a `stage` whose `branches` match the PR's base branch (a stage
   without branches is a later step, never held at merge); `when` on the work ticket's `issue_types` and `projects`;
   gates `approved_on: work`, checked on the work ticket itself and needing no line; `approved_field` values; and
   `github_review`, an approving review of the head commit from an active member of the approvers' GitHub team
   (`review-token`). Data a v2 rule needs that can't be read applies the gate, or leaves it unverified.
8. The PR's shape (pr_shape.py, settings from AGENTS.md at the base commit): within its diff budget unless the body has
   a `Budget: <reason>` line, no hand-edited generated files, and a `changes/<KEY>.md` fragment when it changes source.
9. With `artifact-receipt` (receipt.py, KAN-558): the artifact check's receipt is there, well formed, and passed.
   It holds on every PR, exempt ones too; a missing receipt passes with a warning only under `allow-unverified`.

Exempt: PRs with the exemption label (default `no-ticket`) and PRs by the exempt authors (default the dependency
bots) skip rules 1-6; the org's gates (rule 7) still hold, since an exemption is about the ticket, not the approvals.
Rule 8 holds on a `no-ticket` PR too (without a key, no fragment is asked for); the exempt authors skip it.
Reads the event payload, the PR's file list and reviews through the GitHub API, the org file and AGENTS.md, and the
tracker through tracker.py, only with GET;
writes nothing except the job summary.
"""

from __future__ import annotations

import base64
import http.client
import fnmatch
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from importlib.util import module_from_spec, spec_from_file_location

# the tracker role (KAN-437): loaded by path, next to this file, so the action needs no package or sys.path entry
_spec = spec_from_file_location("work_system_pr_tracker", os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                                                       "tracker.py"))
tracker = module_from_spec(_spec)  # type: ignore[arg-type]
_spec.loader.exec_module(tracker)  # type: ignore[union-attr]

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pr_shape  # noqa: E402  (rule 8, beside this file)
import receipt  # noqa: E402  (rule 9, beside this file)

DEFAULT_KEY = r"[A-Z][A-Z0-9]{1,9}-[0-9]+"
EXEC_PREFIXES = ("exec:", "lane:")  # execution labels; lane:* is the older name, accepted while Jira is relabelled


@dataclass
class Result:
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    key: str | None = None
    exempt: str | None = None


def _line(body: str, name: str) -> str | None:
    m = re.search(rf"(?mi)^[\s>*_-]*{re.escape(name)}:\s*(.*)$", body or "")
    return m.group(1).strip().strip("*_ ") if m else None


def check_pr(pr: dict, files: list[dict] | None, *, key_pattern: str = DEFAULT_KEY, tracker_line: str = "Jira",
             require_docs: bool = True, adr_dir: str = "docs/decisions", exempt_label: str = "no-ticket",
             exempt_authors: tuple[str, ...] = ("dependabot[bot]", "renovate[bot]")) -> Result:
    r = Result()
    labels = {lab.get("name") for lab in pr.get("labels") or []}
    author = (pr.get("user") or {}).get("login") or ""
    if exempt_label and exempt_label in labels:
        r.exempt = f"label {exempt_label!r}"
        return r
    if author in exempt_authors:
        r.exempt = f"author {author}"
        return r
    title, body, branch = pr.get("title") or "", pr.get("body") or "", (pr.get("head") or {}).get("ref") or ""

    m = re.match(rf"^\s*\[?({key_pattern})\]?[:\s]", title)
    if not m:
        r.errors.append(f"the title must start with the ticket key, like 'KAN-123: what changes' (got {title!r}); "
                        f"for work that deliberately has no ticket, add the {exempt_label!r} label")
        return r
    r.key = key = m.group(1)

    line = _line(body, tracker_line)
    if line is None:
        r.errors.append(f"the body needs a '{tracker_line}: {key}' line")
    elif not re.match(rf"^{re.escape(key)}\b", line):
        r.errors.append(f"the '{tracker_line}:' line says {line!r}; it must name the title's key {key}")

    if require_docs:
        docs = _line(body, "Docs")
        if not docs:
            r.errors.append("the body needs a 'Docs:' line: the docs or ADR files changed, a Confluence page, "
                            "or 'none needed - <why>'")
        elif re.match(r"(?i)^none(\s+needed)?\W*$", docs):
            r.errors.append("'Docs: none needed' must say why, like 'none needed - internal refactor'")

    decision = _line(body, "Decision")
    if decision:
        dm = re.match(rf"^({key_pattern})", decision)
        if not dm:
            r.errors.append(f"the 'Decision:' line must name a Decision ticket key (got {decision!r})")
        elif files is None:
            r.warnings.append("could not list the PR's files, so the ADR for the Decision was not checked")
        else:
            dkey = dm.group(1)
            adrs = [f for f in files if f.get("filename", "").startswith(adr_dir.rstrip("/") + "/")
                    and f.get("status") != "removed"]
            if not adrs:
                r.errors.append(f"the PR implements Decision {dkey} but adds or changes no ADR under {adr_dir}/")
            elif not any(dkey in (f.get("patch") or "") for f in adrs):
                r.errors.append(f"no ADR changed under {adr_dir}/ mentions {dkey}; link the Decision in the ADR")

    if key not in branch:
        r.warnings.append(f"the branch {branch!r} does not contain {key}; name branches '{key}-<slug>' where you can")
    return r


def _is_decision(item: dict) -> bool:
    return item.get("kind") == "decision" or "type:decision" in item.get("labels", [])


def check_ticket(issue: dict, key: str) -> list[str]:
    """Rule 6, from the ticket as tracker.py normalises it (key, status, category, kind, labels, blocked_by)."""
    errs = []
    if issue["category"] == "done":
        errs.append(f"{key} is {issue['status']}: reopen it or file a new ticket")
    if issue["kind"] != "work":
        errs.append(f"{key} is a {issue['kind']}; a PR implements a story, task or bug "
                    f"(use 'Decision: {key}' for a decision)")
    elif _is_decision(issue):
        errs.append(f"{key} is a decision (type:decision); a PR implements a story, task or bug "
                    f"(use 'Decision: {key}' for a decision)")
    if not any(lab.startswith(EXEC_PREFIXES) for lab in issue["labels"]):
        errs.append(f"{key} has no execution label (exec:agent, exec:pair or exec:human; lane:* is still accepted)")
    for b in issue["blocked_by"]:
        if _is_decision(b) and b["category"] != "done":
            errs.append(f"{key} is blocked by open Decision {b['key']}: answer it before merging")
    return errs


# --- rule 7: the org's merge gates -----------------------------------------------------------------------------------

ORG_SCHEMA_V1 = "team-harness.org/v1"
ORG_SCHEMA = "team-harness.org/v2"
ORG_KEYS_V1 = {"schema", "name", "placeholder", "params", "ticket_types", "gates", "review_request"}
ORG_KEYS = ORG_KEYS_V1 | {"reviewers", "stages"}
TICKET_TYPE_KEYS = {"id", "project", "issue_type", "role", "summary"}
GATE_KEYS_V1 = {"id", "ticket", "when", "pr_line", "links", "filed_by", "approved_statuses"}
GATE_KEYS = GATE_KEYS_V1 | {"approved_on", "approvers", "needs_approval", "github_review", "scope", "stage",
                            "approved_field"}
WHEN_KEYS_V1 = {"paths", "labels"}
WHEN_KEYS = WHEN_KEYS_V1 | {"issue_types", "projects"}
REVIEWER_KEYS = {"name", "github_team"}
STAGE_KEYS = {"name", "branches"}
GITHUB_TEAM = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]*/[A-Za-z0-9][A-Za-z0-9_.-]*$")
LINK_KINDS = {"pr", "work", "repo"}
ROLES = {"work", "approval"}
FILED_BY = {"agent", "person"}
RESERVED_PR_LINES = {"jira", "docs", "decision"}  # the check's own lines (and the tracker line, passed in)


class OrgError(ValueError):
    """The org file can't be used; the message says why."""


def _str_list(v: object, where: str) -> list[str]:
    if not isinstance(v, list) or not v or not all(isinstance(x, str) and x.strip() for x in v):
        raise OrgError(f"{where} must be a non-empty list of strings")
    return list(v)


def _unknown(d: dict, allowed: set[str], where: str) -> None:
    if True in d:
        raise OrgError(f"{where} has a key that reads as true: YAML reads `on:` as a boolean (write approved_on:)")
    extra = sorted(str(k) for k in d if k not in allowed)
    if extra:
        raise OrgError(f"{where} has unknown key(s) {', '.join(extra)} (allowed: {', '.join(sorted(allowed))})")


def validate_org(data: object, *, tracker_line: str = "Jira") -> dict:
    """Check the parts of an org.yaml (team-harness.org/v1) the PR check relies on; raise OrgError with the reason.
    Kept in step with scripts/sync_shared.py's validator: `when` and `filed_by` are required, a gate's pr_line may not
    be one of the check's own lines, and there is at least one gate."""
    reserved = RESERVED_PR_LINES | {tracker_line.lower()}
    if not isinstance(data, dict):
        raise OrgError("the org file must be a mapping at the top level")
    if data.get("schema") not in (ORG_SCHEMA, ORG_SCHEMA_V1):
        raise OrgError(f"schema must be {ORG_SCHEMA!r} or {ORG_SCHEMA_V1!r} (got {data.get('schema')!r})")
    v2 = data["schema"] == ORG_SCHEMA
    _unknown(data, ORG_KEYS if v2 else ORG_KEYS_V1, "the org file")
    if not isinstance(data.get("name"), str) or not data["name"].strip():
        raise OrgError("name must be a non-empty string")
    if not isinstance(data.get("placeholder", False), bool):
        raise OrgError("placeholder must be true or false")
    for opt, kind in (("params", dict), ("review_request", dict)):
        if opt in data and not isinstance(data[opt], kind):
            raise OrgError(f"{opt} must be a mapping")
    types = data.get("ticket_types")
    if not isinstance(types, list) or not types:
        raise OrgError("ticket_types must be a non-empty list")
    by_id: dict[str, dict] = {}
    for i, t in enumerate(types):
        where = f"ticket_types[{i}]"
        if not isinstance(t, dict):
            raise OrgError(f"{where} must be a mapping")
        _unknown(t, TICKET_TYPE_KEYS, where)
        for k in ("id", "project", "issue_type", "role"):
            if not isinstance(t.get(k), str) or not t[k].strip():
                raise OrgError(f"{where} needs a non-empty {k!r}")
        if t["role"] not in ROLES:
            raise OrgError(f"{where} role must be one of {', '.join(sorted(ROLES))} (got {t['role']!r})")
        if t["id"] in by_id:
            raise OrgError(f"ticket type id {t['id']!r} is used twice")
        by_id[t["id"]] = t
    reviewers = _reviewers(data) if v2 else {}
    stages = _stages(data) if v2 else set()
    gates = data.get("gates")
    if not isinstance(gates, list) or not gates:
        raise OrgError("gates must list at least one gate")
    seen_ids: set[str] = set()
    seen_lines: set[str] = set()
    for i, g in enumerate(gates):
        where = f"gates[{i}]"
        if not isinstance(g, dict):
            raise OrgError(f"{where} must be a mapping")
        _unknown(g, GATE_KEYS if v2 else GATE_KEYS_V1, where)
        if v2 and g.get("approved_on", "ticket") not in ("ticket", "work"):
            raise OrgError(f"{where} approved_on must be ticket or work")
        on_work = v2 and g.get("approved_on") == "work"
        for k in ("id",) if on_work else ("id", "ticket", "pr_line", "filed_by"):
            if not isinstance(g.get(k), str) or not g[k].strip():
                raise OrgError(f"{where} needs a non-empty {k!r}")
        where = f"gate {g['id']!r}"
        if g["id"] in seen_ids:
            raise OrgError(f"gate id {g['id']!r} is used twice")
        seen_ids.add(g["id"])
        if not on_work:
            if g["pr_line"].lower() in seen_lines:
                raise OrgError(f"pr_line {g['pr_line']!r} is used by two gates")
            if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]*", g["pr_line"]):
                raise OrgError(f"{where} pr_line {g['pr_line']!r} must be a plain name, like 'SRE'")
            if g["pr_line"].lower() in reserved:
                raise OrgError(f"{where} pr_line {g['pr_line']!r} is one of the PR check's own lines")
            seen_lines.add(g["pr_line"].lower())
            t = by_id.get(g["ticket"])
            if t is None:
                raise OrgError(f"{where} names unknown ticket type {g['ticket']!r}")
            if t["role"] != "approval":
                raise OrgError(f"{where} uses ticket type {g['ticket']!r}, which is role {t['role']!r}, not "
                               "'approval'")
            if g["filed_by"] not in FILED_BY:
                raise OrgError(f"{where} filed_by must be agent or person (got {g.get('filed_by')!r})")
        _when(g, where, v2)
        if "links" in g:
            bad = [x for x in _str_list(g["links"], f"{where} links") if x not in LINK_KINDS]
            if bad:
                raise OrgError(f"{where} links has {', '.join(bad)} (allowed: {', '.join(sorted(LINK_KINDS))})")
        if "approved_statuses" in g:
            _str_list(g["approved_statuses"], f"{where} approved_statuses")
        if v2:
            _gate_v2(g, where, by_id, reviewers, stages)
    return data


def _when(g: dict, where: str, v2: bool) -> None:
    shapes = "always, {paths: [...]}, {labels: [...]}" + (", {issue_types: [...]}, {projects: [...]}" if v2 else "")
    if "when" not in g:
        raise OrgError(f"{where} needs a 'when' ({shapes})")
    when = g["when"]
    if when != "always":
        if not isinstance(when, dict) or not when:
            raise OrgError(f"{where} when must be one of {shapes}")
        _unknown(when, WHEN_KEYS if v2 else WHEN_KEYS_V1, f"{where} when")
        for k in when:
            _str_list(when[k], f"{where} when.{k}")


def _reviewers(data: dict) -> dict[str, dict]:
    reviewers = data.get("reviewers", {})
    if not isinstance(reviewers, dict):
        raise OrgError("reviewers must be a mapping of review team ids")
    for rid, r in reviewers.items():
        if not isinstance(rid, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", rid):
            raise OrgError(f"reviewers id {rid!r} must be lower case letters, digits and -")
        if not isinstance(r, dict):
            raise OrgError(f"reviewers.{rid} must be a mapping with name")
        _unknown(r, REVIEWER_KEYS, f"reviewers.{rid}")
        if not isinstance(r.get("name"), str) or not r["name"].strip():
            raise OrgError(f"reviewers.{rid} needs a non-empty 'name'")
        if "github_team" in r and (not isinstance(r["github_team"], str) or not GITHUB_TEAM.match(r["github_team"])):
            raise OrgError(f"reviewers.{rid} github_team must be <org>/<team-slug>")
    return reviewers


def _stages(data: dict) -> set[str]:
    stages = data.get("stages", [])
    if not isinstance(stages, list):
        raise OrgError("stages must be a list of {name, branches}")
    names: set[str] = set()
    for i, st in enumerate(stages):
        if not isinstance(st, dict):
            raise OrgError(f"stages[{i}] must be a mapping")
        _unknown(st, STAGE_KEYS, f"stages[{i}]")
        if not isinstance(st.get("name"), str) or not st["name"].strip() or st["name"] in names:
            raise OrgError(f"stages[{i}] needs a unique non-empty 'name'")
        names.add(st["name"])
        if "branches" in st:
            _str_list(st["branches"], f"stages[{i}] branches")
    return names


def _gate_v2(g: dict, where: str, types: dict[str, dict], reviewers: dict[str, dict], stages: set[str]) -> None:
    """The v2 keys of one gate; kept in step with scripts/sync_shared.py's _validate_gate_v2."""
    on = g.get("approved_on", "ticket")
    if on not in ("ticket", "work"):
        raise OrgError(f"{where} approved_on must be ticket or work")
    for k in ("needs_approval", "github_review"):
        if k in g and not isinstance(g[k], bool):
            raise OrgError(f"{where} {k} must be true or false")
    needs, review, scope = g.get("needs_approval", True), g.get("github_review", False), g.get("scope", "pr")
    if scope not in ("pr", "repo"):
        raise OrgError(f"{where} scope must be pr or repo")
    if "approvers" in g and g["approvers"] not in reviewers:
        raise OrgError(f"{where} approvers {g['approvers']!r} is not a reviewers id")
    if review and not (reviewers.get(g.get("approvers", "")) or {}).get("github_team"):
        raise OrgError(f"{where} github_review needs approvers with a github_team")
    if "stage" in g and g["stage"] not in stages:
        raise OrgError(f"{where} stage {g['stage']!r} is not one of the stages")
    field = g.get("approved_field")
    if field is not None and (not isinstance(field, dict) or set(field) != {"field", "values"}
                              or not isinstance(field.get("field"), str) or not tracker.FIELD_ID.match(field["field"])):
        raise OrgError(f"{where} approved_field must be {{field: <the tracker's field id>, values: [names]}}")
    if field is not None:
        _str_list(field["values"], f"{where} approved_field.values")
    approved = "approved_statuses" in g or field is not None
    if not needs and (approved or review):
        raise OrgError(f"{where} needs_approval: false takes no approved_statuses, approved_field or github_review")
    links = g.get("links", [])
    if on == "work":
        extra = [k for k in ("ticket", "pr_line", "filed_by") if k in g]
        if extra:
            raise OrgError(f"{where} is approved on the work ticket, so it has no {', '.join(extra)}")
        if not any(t.get("role") == "work" for t in types.values()):
            raise OrgError(f"{where} approved_on: work needs a ticket type with role work")
        if scope != "pr" or (isinstance(links, list) and set(links) - {"pr"}) or not needs \
                or not (approved or review):
            raise OrgError(f"{where} approved_on: work is per PR, links only pr, and needs approved_statuses, "
                           "approved_field or github_review")
        if approved and not (isinstance(links, list) and "pr" in links):
            raise OrgError(f"{where} approved_on: work gate approved in Jira needs links: [pr], so the approval is for "
                           "this PR's work ticket")
    elif scope == "repo" and isinstance(links, list) and (set(links) & {"pr", "work"} or "repo" not in links):
        raise OrgError(f"{where} scope: repo shares one ticket across the repository's PRs, so it links repo only")


def load_org(path: str, *, tracker_line: str = "Jira") -> dict:
    """Read and validate an org file from disk (see parse_org)."""
    try:
        with open(path, encoding="utf-8") as fh:
            text = fh.read()
    except OSError as e:
        raise OrgError(f"the org file {path} could not be read ({e.strerror or e})") from None
    return parse_org(text, path, tracker_line=tracker_line)


def parse_org(text: str, path: str, *, tracker_line: str = "Jira") -> dict:
    """Parse and validate an org file's text. YAML needs PyYAML (action.yml installs a pinned one when it's missing);
    without it a JSON org file still works, since JSON is YAML."""
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError:
        try:
            data = json.loads(text)
        except ValueError:
            raise OrgError(f"the org file {path} is not JSON and PyYAML is not installed to read it as YAML") from None
    else:
        try:
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise OrgError(f"the org file {path} is not valid YAML: {str(e).splitlines()[0]}") from None
    return validate_org(data, tracker_line=tracker_line)


@dataclass
class Gate:
    id: str
    pr_line: str
    ticket: str
    project: str
    issue_type: str
    filed_by: str
    applies: bool
    why: str             # why it applies (or not)
    key: str | None = None
    state: str = ""      # not required | missing | pending | invalid | linked | checked | not approved | unverified
    #                      | not enforced | not checked
    errors: list[str] = field(default_factory=list)
    on: str = "ticket"   # ticket: a separate approval ticket | work: approved on the work ticket (v2)
    approvers: str = ""  # the review team's name (v2)
    record_only: bool = False  # needs_approval: false (v2): filed for the record, nothing waits on its approval


def _changed_paths(files: list[dict]) -> list[str]:
    out = []
    for f in files:
        out += [p for p in (f.get("filename"), f.get("previous_filename")) if p]
    return out


def _glob_variants(pattern: str) -> set[str]:
    """`**/` also matches no directory at all, so `**/Dockerfile` matches `Dockerfile` and `a/**/b` matches `a/b`."""
    out, todo = set(), [pattern]
    while todo:
        p = todo.pop()
        if p in out:
            continue
        out.add(p)
        if p.startswith("**/"):
            todo.append(p[3:])
        i = p.find("/**/")
        while i != -1:
            todo.append(p[:i] + p[i + 3:])
            i = p.find("/**/", i + 1)
    return out


def path_matches(path: str, pattern: str) -> bool:
    return any(fnmatch.fnmatchcase(path, v) for v in _glob_variants(pattern))


def _applies(when: object, labels: set[str], files: list[dict] | None,
             work_labels: Iterable[str] | None = (), work_issue_type: str | None = "",
             work_project: str | None = "") -> tuple[bool, str]:
    """Any match applies the gate. Labels compare case-insensitively and come from the PR and its work ticket; issue
    types (case-insensitive) and projects come from the work ticket. `files`, `work_labels`, `work_issue_type` or
    `work_project` None means it could not be read, and then the gate applies (fail closed)."""
    if when == "always" or when is None:
        return True, "always"
    assert isinstance(when, dict)
    hits: list[str] = []
    unknown: list[str] = []
    if "labels" in when:
        want = {lab.lower() for lab in when["labels"]}
        hits += [f"label {lab}" for lab in sorted(labels) if lab and lab.lower() in want]
        if work_labels is None:
            unknown.append("labels (the work ticket's labels could not be read, so the gate applies)")
        else:
            hits += [f"work ticket label {lab}" for lab in sorted(set(work_labels)) if lab.lower() in want]
    if "issue_types" in when:
        if work_issue_type is None:
            unknown.append("issue types (the work ticket's issue type is unknown: unread, or no work ticket; so the gate applies)")
        elif work_issue_type.lower() in {t.lower() for t in when["issue_types"]}:
            hits.append(f"work ticket type {work_issue_type}")
    if "projects" in when:
        if work_project is None:
            unknown.append("projects (the work ticket's project is unknown: the PR names no work ticket; so the gate applies)")
        elif work_project.upper() in {p.upper() for p in when["projects"]}:
            hits.append(f"work ticket project {work_project}")
    if "paths" in when:
        if files is None:
            unknown.append("paths (the PR's files could not be listed, so the gate applies)")
        else:
            paths = _changed_paths(files)
            hits += [f"path {p}" for p in paths if any(path_matches(p, g) for g in when["paths"])][:3]
    if hits:
        return True, ", ".join(hits)
    if unknown:
        return True, unknown[0]
    return False, "no matching " + " or ".join(sorted(when))


def _stage(g: dict, stages: dict[str, dict], base_ref: str | None) -> tuple[bool, str]:
    """Whether the gate's stage is this PR's: a stage with branches is checked when the PR merges into one of them; a
    stage without branches is a later step (a release) the PR check doesn't hold the merge for. No stage: every
    stage. An unknown base branch applies the gate (fail closed)."""
    name = g.get("stage")
    if not name:
        return True, ""
    branches = (stages.get(name) or {}).get("branches") or []
    if not branches:
        return False, f"stage {name} is a later step (a release), not held at merge"
    if not base_ref:
        return True, f"stage {name} (the PR's base branch is unknown, so the gate applies)"
    if any(fnmatch.fnmatchcase(base_ref, b) for b in branches):
        return True, f"stage {name}"
    return False, f"stage {name} merges into {', '.join(branches)}, not {base_ref}"


def _no_comments(body: str) -> str:
    # an unclosed `<!--` hides the rest of the body when GitHub renders it, so it hides it from the check too
    return re.sub(r"(?s)<!--.*?(?:-->|\Z)", "", body or "")


@dataclass
class GateContext:
    """What the tracker side of rule 7 needs. `tickets` reads a gate ticket through tracker.py's provider, as a
    normalised gate ticket (`gate_issue`) and its remote links as text (`gate_links`); None when it has no
    credentials. `fields` are the org's approved_field ids, asked for on every read."""
    tickets: object | None = None
    fields: tuple[str, ...] = ()
    label: str = ""
    work_key: str | None = None
    pr_url: str = ""
    allow_unverified: bool = False
    repo_url: str = ""
    # github_review (v2): `reviews()` lists the PR's reviews in the order they were submitted; `team_member(team,
    # login)` says whether the login is an active member of `org/team-slug`. Both GETs; None when not given.
    reviews: Callable[[], object] | None = None
    team_member: Callable[[str, str], bool] | None = None
    head_sha: str = ""
    author: str = ""


def _repo_url(pr: dict) -> str:
    """The base repository's web URL: the payload's own, or the PR URL without its `/pull/N`."""
    url = str(((pr.get("base") or {}).get("repo") or {}).get("html_url") or "")
    if not url:
        m = re.match(r"^(https?://[^/]+/[^/]+/[^/]+)/pull/\d+/?$", str(pr.get("html_url") or ""))
        url = m.group(1) if m else ""
    return url.rstrip("/")


def _needs_tracker(g: dict) -> bool:
    """A gate whose rule only the tracker can show (an approved status or field, a link) fails when its ticket can't be
    read."""
    return bool(g.get("approved_statuses") or g.get("links") or g.get("approved_field"))


def check_gates(pr: dict, files: list[dict] | None, org: dict, *, key_pattern: str = DEFAULT_KEY,
                tickets: object | None = None, tracker_label: str | None = None,
                fetch: Callable[[str], object] | None = None, remote_links: Callable[[str], object] | None = None,
                work_key: str | None = None, work_labels: Iterable[str] | None = (),
                work_issue_type: str | None = "", allow_unverified: bool = False,
                reviews: Callable[[], object] | None = None,
                team_member: Callable[[str, str], bool] | None = None) -> tuple[list[Gate], list[str], list[str]]:
    """Rule 7. Returns the gates with their state, errors and warnings. Fails closed: a gate whose approval can't be
    verified fails unless `allow_unverified` is set. `work_issue_type` None means the work ticket's issue type could
    not be read (gates with `when: issue_types` then apply).

    `tickets` is a tracker.py provider or reader with `gate_issue` and `gate_links`; `fetch` and `remote_links`
    (Jira's raw answers) are kept for callers that hold them, and go through the jira-cloud provider's mapping."""
    errors: list[str] = []
    warnings: list[str] = []
    if tickets is None and fetch is not None:
        tickets = tracker.JiraAnswers(fetch, remote_links)
    label = tracker_label or getattr(tickets, "label", None) or tracker.PROVIDERS[tracker.DEFAULT_PROVIDER].label
    reader = tracker.gate_reader(tickets) if tickets is not None else None
    ids = tuple(sorted({g["approved_field"]["field"] for g in org.get("gates") or [] if g.get("approved_field")}))
    ctx = GateContext(reader, ids, label, work_key, str(pr.get("html_url") or ""), allow_unverified, _repo_url(pr),
                      reviews, team_member, str((pr.get("head") or {}).get("sha") or ""),
                      str((pr.get("user") or {}).get("login") or ""))
    types = {t["id"]: t for t in org["ticket_types"]}
    work_types = [t for t in org["ticket_types"] if t["role"] == "work"]
    reviewers = org.get("reviewers") or {}
    stages = {st["name"]: st for st in org.get("stages") or []}
    base_ref = (pr.get("base") or {}).get("ref") or None
    work_project = work_key.rsplit("-", 1)[0] if work_key else None  # no work ticket: project gates apply
    labels = {str(lab.get("name") or "") for lab in pr.get("labels") or []}
    body = _no_comments(pr.get("body") or "")
    placeholder = bool(org.get("placeholder"))
    if placeholder:
        warnings.append(f"the org overlay {org['name']!r} is a placeholder (placeholder: true); its merge gates are "
                        "not enforced until the company's own org.yaml replaces it")
    if files is None and any(isinstance(g.get("when"), dict) and "paths" in g["when"] for g in org.get("gates") or []):
        warnings.append("could not list the PR's files, so every gate with `when: paths` applies")
    gates: list[Gate] = []
    for g in org.get("gates") or []:
        on_work = g.get("approved_on") == "work"
        applies, why = _stage(g, stages, base_ref)
        if applies:
            when_applies, when_why = _applies(g.get("when", "always"), labels, files, work_labels, work_issue_type,
                                              work_project)
            applies, why = when_applies, f"{why}; {when_why}" if why else when_why
        if on_work:
            t = work_types[0]
            gate = Gate(g["id"], "", t["id"], t["project"], t["issue_type"], "-", applies, why, on="work")
        else:
            t = types[g["ticket"]]
            gate = Gate(g["id"], g["pr_line"], t["id"], t["project"], t["issue_type"], g.get("filed_by", "agent"),
                        applies, why)
        gate.approvers = (reviewers.get(g.get("approvers") or "") or {}).get("name", "")
        gate.record_only = g.get("needs_approval") is False
        gates.append(gate)
        if not applies:
            gate.state = "not required"
            continue
        if placeholder:
            gate.state = "not enforced"
            continue
        if on_work:
            _check_work_gate(gate, g, work_types, reviewers, ctx, warnings)
            errors += gate.errors
            continue
        what = (f"gate {gate.id!r} needs a '{gate.pr_line}: <KEY>' line naming its {t['issue_type']} "
                f"({gate.ticket}) in {gate.project}")
        how = ("a person files that ticket: ask in the PR, then add its key" if gate.filed_by == "person"
               else "file the approval ticket and link it here")
        value = _line(body, gate.pr_line)
        m = re.match(rf"^({key_pattern})\b", value or "")
        if value is None or not value:
            gate.state = "missing"
            gate.errors.append(f"{what}; {how} (the PR can't merge until it is)")
        elif re.match(r"(?i)^pending\b", value):
            gate.state = "pending"
            gate.errors.append(f"{what}, but it says pending; {how} (the PR can't merge until it is)")
        elif not m:
            gate.state = "invalid"
            gate.errors.append(f"{what}; the '{gate.pr_line}:' line says {value!r}, which is not a ticket key")
        else:
            gate.key = key = m.group(1)
            gate.state = "linked"
            if not key.startswith(gate.project + "-"):
                gate.state = "invalid"
                gate.errors.append(f"gate {gate.id!r}: {gate.key} is not in {gate.project}, where the "
                                   f"{gate.ticket} ticket is filed")
            elif ctx.tickets is None:
                if _needs_tracker(g):
                    _unverified(gate, f"there are no {ctx.label} credentials to read it (fork and bot PRs get no "
                                "secrets)", g, ctx, errors=gate.errors, warnings=warnings)
            else:
                _check_gate_ticket(gate, g, t, ctx, warnings)
                if not gate.errors and gate.state == "linked":
                    gate.state = "checked"
            if g.get("github_review") and gate.state != "invalid":
                _check_review(gate, reviewers[g["approvers"]]["github_team"], ctx, warnings)
        errors += gate.errors
    return gates, errors, warnings


def _check_work_gate(gate: Gate, g: dict, work_types: list[dict], reviewers: dict[str, dict], ctx: GateContext,
                     warnings: list[str]) -> None:
    """An `approved_on: work` gate: the approval is recorded on the work ticket itself (its status or a field), the
    work ticket links the PR, and, with github_review, a member of the approvers' GitHub team approved the PR."""
    if not ctx.work_key:
        gate.state = "invalid"
        gate.errors.append(f"gate {gate.id!r} is approved on the work ticket, but the PR names no work ticket; put "
                           "its key in the title")
        return
    gate.key = ctx.work_key
    gate.state = "linked"
    projects = sorted({t["project"] for t in work_types})
    if ctx.work_key.rsplit("-", 1)[0] not in projects:
        gate.state = "invalid"
        gate.errors.append(f"gate {gate.id!r} is approved on the work ticket, but {ctx.work_key} is not in "
                           f"{' or '.join(projects)}, where work tickets are filed")
        return
    if _needs_tracker(g):
        if ctx.tickets is None:
            _unverified(gate, f"there are no {ctx.label} credentials to read it (fork and bot PRs get no secrets)", g,
                        ctx, errors=gate.errors, warnings=warnings)
        else:
            _check_gate_ticket(gate, g, None, ctx, warnings)
            if not gate.errors and gate.state == "linked":
                gate.state = "checked"
    if g.get("github_review") and gate.state != "invalid":
        _check_review(gate, reviewers[g["approvers"]]["github_team"], ctx, warnings)
        if not gate.errors and gate.state == "linked":
            gate.state = "checked"  # approved on GitHub: the summary must not read as merely linked


_DECISIVE = {"APPROVED", "CHANGES_REQUESTED", "DISMISSED"}  # a COMMENTED review leaves a reviewer's verdict as it was


def _check_review(gate: Gate, team: str, ctx: GateContext, warnings: list[str]) -> None:
    """github_review: a member of `team` (org/team-slug) approved the PR, and that approval is their latest verdict
    and is on the PR's head commit (a push after it needs a new approval). The PR's author never counts. Reviews or
    membership that can't be read fail the gate unless allow-unverified is set."""
    what = f"approved on GitHub by a member of @{team}"
    if ctx.reviews is None or ctx.team_member is None:
        _unverified(gate, "the check was given no way to read the PR's reviews", {}, ctx, errors=gate.errors,
                    warnings=warnings, what=what)
        return
    try:
        answer = ctx.reviews()
        if not isinstance(answer, list):
            raise ValueError("the reviews API did not return a list")
    except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
        _unverified(gate, f"the PR's reviews could not be read ({e})", {}, ctx, errors=gate.errors,
                    warnings=warnings, what=what)
        return
    latest: dict[str, dict] = {}
    for r in answer:
        login = str(((r or {}).get("user") or {}).get("login") or "") if isinstance(r, dict) else ""
        if login and r.get("state") in _DECISIVE:
            latest[login] = r
    approved = [login for login, r in latest.items() if r.get("state") == "APPROVED" and login != ctx.author]
    current = [login for login in approved if ctx.head_sha and latest[login].get("commit_id") == ctx.head_sha]
    objecting = [login for login, r in latest.items() if r.get("state") == "CHANGES_REQUESTED" and login != ctx.author]
    members: dict[str, bool] = {}
    for login in current + objecting:
        try:
            members[login] = bool(ctx.team_member(team, login))
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            _unverified(gate, f"whether {login} is on @{team} could not be read ({e}); the review token needs to "
                        "read the organisation's teams", {}, ctx, errors=gate.errors, warnings=warnings, what=what)
            return
    blocking = [login for login in objecting if members[login]]
    if blocking:  # as on GitHub: a member's request for changes holds until they approve or it is dismissed
        if gate.state in ("linked", "checked"):
            gate.state = "not approved"
        gate.errors.append(f"gate {gate.id!r}: {', '.join(blocking)} of @{team} requested changes; the PR needs "
                           "their approval (or the review dismissed), then re-run the check")
        return
    if any(members[login] for login in current):
        return
    outsiders = [login for login in current if not members[login]]
    if gate.state in ("linked", "checked"):
        gate.state = "not approved"
    why = []
    if outsiders:
        why.append(f"{', '.join(outsiders)} approved but {'is' if len(outsiders) == 1 else 'are'} not on @{team}")
    stale = [login for login in approved if login not in current]
    if stale:
        why.append(f"{', '.join(stale)} approved an earlier commit")
    gate.errors.append(f"gate {gate.id!r} needs an approving review on the PR's latest commit from a member of "
                       f"@{team}" + (f" ({'; '.join(why)})" if why else "") + "; request one, then re-run the check")


def _what_tracker_shows(g: dict) -> str:
    parts = []
    if g.get("approved_statuses"):
        parts.append(" or ".join(g["approved_statuses"]))
    if g.get("approved_field"):
        parts.append(f"{g['approved_field']['field']} {' or '.join(g['approved_field']['values'])}")
    if g.get("links"):
        names = {"pr": "the PR", "work": "the work ticket", "repo": "the repository"}
        parts.append("linking " + " and ".join(names.get(x, f"the {x}") for x in g["links"]))
    return ", ".join(parts)


def _unverified(gate: Gate, why: str, g: dict, ctx: GateContext, *, errors: list[str],
                warnings: list[str], what: str = "") -> None:
    """A gate that needs the tracker (an approval, a link) whose ticket couldn't be read, or a GitHub review that couldn't
    be read: fail, unless allow-unverified."""
    msg = (f"gate {gate.id!r}: {gate.key} could not be verified as {what or _what_tracker_shows(g)} because {why}")
    if ctx.allow_unverified:
        gate.state = "not checked"  # passes unread; the summary must not say checked
        warnings.append(f"{msg}; passing it unverified because allow-unverified is set")
    else:
        gate.state = "unverified"
        errors.append(f"{msg}; the PR can't merge until the check reads it (re-run the check, or set "
                      "allow-unverified for repositories that knowingly accept this)")


def _mentions(text: object, url: str, *, ignore_case: bool = False) -> bool:
    """Whether the text (a description or remote links; anything else is read as its JSON) names this URL itself:
    `/pull/7` is not `/pull/70`, and `o/r` is not `o/r-fork`, `o/r2`, `o/r.x` or `o/r%2Dfork` (a link into the
    repository, such as `o/r/pull/7`, names it, and so does a URL that ends a sentence with a full stop)."""
    url = url.rstrip("/")
    flags = re.IGNORECASE if ignore_case else 0
    hay = text if isinstance(text, str) else json.dumps(text or "")
    return bool(url) and re.search(re.escape(url) + r"(?![\w%-]|\.[\w-])", hay, flags) is not None


def _check_gate_ticket(gate: Gate, g: dict, t: dict | None, ctx: GateContext, warnings: list[str]) -> None:
    """The gate ticket, read through the tracker: project, issue type, links, approved status and field. `t` None: the
    gate is approved on the work ticket itself, whose project the caller checked and whose type and work link don't
    apply."""
    approved: list[str] | None = g.get("approved_statuses")
    tickets = ctx.tickets
    assert tickets is not None

    def unreadable(why: str) -> None:
        if _needs_tracker(g):
            _unverified(gate, why, g, ctx, errors=gate.errors, warnings=warnings)
        else:
            gate.state = "not checked"  # passes on the key prefix; the summary must not say checked
            warnings.append(f"gate {gate.id!r}: {gate.key} was not checked because {why}")

    try:
        issue = tickets.gate_issue(gate.key or "", ctx.fields)  # type: ignore[attr-defined]
    except tracker.TicketMissing as e:
        gate.state = "invalid"
        gate.errors.append(f"gate {gate.id!r}: {gate.key} could not be read from {ctx.label} ({e}): "
                           "does the ticket exist, and can the check's account browse its project?")
        return
    except tracker.TrackerUnreachable as e:  # down, or not JSON (an SSO page)
        unreadable(f"{ctx.label} did not answer with the ticket ({e})")
        return
    except tracker.BadAnswer as e:  # fails the gate, never passes it
        unreadable(f"{ctx.label}'s answer could not be used ({e})")
        return
    errs = []
    if t is not None:
        project = issue["project"]
        if project != gate.project:
            gate.state = "invalid"
            errs.append(f"gate {gate.id!r}: {gate.key} is in {project or 'an unknown project'}, not {gate.project}, "
                        f"where the {gate.ticket} ticket is filed")
        itype = issue["issue_type"]
        if itype.lower() != t["issue_type"].lower():
            gate.state = "invalid"
            errs.append(f"gate {gate.id!r}: {gate.key} is a {itype or 'ticket without an issue type'}, not a "
                        f"{t['issue_type']}; file a {t['issue_type']} ({gate.ticket}) for this PR")
    links = g.get("links") or []
    if "work" in links and t is not None:
        if not ctx.work_key:
            gate.state = "invalid"
            errs.append(f"gate {gate.id!r}: the PR names no work ticket, so {gate.key}'s link to it can't be "
                        "checked; put the work key in the title")
        elif ctx.work_key not in issue["links"]:
            gate.state = "invalid"
            errs.append(f"gate {gate.id!r}: {gate.key} has no issue link to the work ticket {ctx.work_key}; link it "
                        f"('relates to') so the approval is for this work")
    remote: list[str | None] = []  # read once, for pr and repo; [None] once reading them failed

    def links_to(url: str, ignore_case: bool = False) -> bool | None:
        """Whether the description or a remote link names the URL; None when the remote links can't be read."""
        if _mentions(issue["text"], url, ignore_case=ignore_case):
            return True
        if not url:
            return False
        if not remote:
            try:
                remote.append(tickets.gate_links(gate.key or ""))  # type: ignore[attr-defined]
            except (tracker.TicketMissing, tracker.TrackerUnreachable, tracker.BadAnswer) as e:
                remote.append(None)
                unreadable(f"its remote links could not be read ({e})")
        if remote[0] is None:
            return None
        return _mentions(remote[0], url, ignore_case=ignore_case)

    if "pr" in links and links_to(ctx.pr_url, ignore_case=True) is False:
        gate.state = "invalid"
        errs.append(f"gate {gate.id!r}: {gate.key} does not link this PR; add {ctx.pr_url or 'the PR URL'} as a "
                    "remote link or in its description")
    if "repo" in links and links_to(ctx.repo_url, ignore_case=True) is False:
        gate.state = "invalid"
        errs.append(f"gate {gate.id!r}: {gate.key} does not name this repository; add "
                    f"{ctx.repo_url or 'the repository URL'} as a remote link or in its description")
    status = issue["status"]
    if approved and status.lower() not in {s.lower() for s in approved}:
        if gate.state == "linked":
            gate.state = "not approved"
        errs.append(f"gate {gate.id!r}: {gate.key} is {status or 'without a status'}; it must be "
                    f"{' or '.join(approved)} before the PR merges")
    field_rule = g.get("approved_field")
    if field_rule:
        name, want = field_rule["field"], field_rule["values"]
        if name not in issue["field_values"]:
            if gate.state == "linked":
                gate.state = "not approved"
            errs.append(f"gate {gate.id!r}: {ctx.label} returned no {name} field for {gate.key}; check the field id, and "
                        f"that the field is on the issue's screen (it must be {' or '.join(want)})")
        else:
            have = issue["field_values"][name]
            if not {v.lower() for v in have} & {v.lower() for v in want}:
                if gate.state == "linked":
                    gate.state = "not approved"
                errs.append(f"gate {gate.id!r}: {gate.key}'s {name} is {', '.join(have) or 'empty'}; it must be "
                            f"{' or '.join(want)} before the PR merges")
    gate.errors += errs


def gate_summary(gates: list[Gate]) -> list[str]:
    if not gates:
        return ["The org file declares no merge gates."]
    rows = ["| Gate | Line | Ticket | Applies | State |", "| --- | --- | --- | --- | --- |"]
    for g in gates:
        if g.on == "work":
            line, ticket = "-", "the work ticket" + (f" {g.key}" if g.key else "")
        else:
            line = f"`{g.pr_line}: {g.key}`" if g.key else f"`{g.pr_line}:`"
            ticket = f"{g.issue_type} in {g.project}" + (" (a person files it)" if g.filed_by == "person" else "")
        if g.approvers:
            ticket += f"; approvers {g.approvers}"
        if g.record_only:
            ticket += "; for the record, nothing waits on its approval"
        applies = ("yes: " if g.applies else "no: ") + g.why
        rows.append(f"| {g.id} | {line} | {ticket.replace('|', '/')} | {applies.replace('|', '/')} | {g.state} |")
    return rows


def _get(url: str, headers: dict[str, str]) -> object:
    req = urllib.request.Request(url, headers={"Accept": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=20) as resp:  # GET only
        return json.load(resp)


def _pr_files(repo: str, number: int, token: str, api: str) -> list[dict] | None:
    out: list[dict] = []
    try:
        for page in range(1, 31):
            batch = _get(f"{api}/repos/{repo}/pulls/{number}/files?per_page=100&page={page}",
                         {"Authorization": f"Bearer {token}"} if token else {})
            out += batch  # type: ignore[operator]
            if len(batch) < 100:  # type: ignore[arg-type]
                return out
    except (urllib.error.URLError, OSError, ValueError):
        return None
    return out


def _github_reviews(repo: str, number: int, token: str, api: str
                    ) -> tuple[Callable[[], object], Callable[[str, str], bool]]:
    """(list the PR's reviews, is this login an active member of org/team) for github_review gates; GET only. A
    membership 404 is "not a member"; the team itself is read first, so a token that can't see the team fails as
    unreadable instead of reading as nobody being on it."""
    auth = {"Authorization": f"Bearer {token}"} if token else {}
    seen_teams: set[str] = set()

    def reviews() -> object:
        out: list[object] = []
        for page in range(1, 31):
            batch = _get(f"{api}/repos/{repo}/pulls/{number}/reviews?per_page=100&page={page}", auth)
            if not isinstance(batch, list):
                raise ValueError("the reviews API did not return a list")
            out += batch
            if len(batch) < 100:
                return out
        raise ValueError("the PR has more than 3000 reviews")

    def member(team: str, login: str) -> bool:
        org, slug = (urllib.parse.quote(p, safe="") for p in team.split("/", 1))
        if team not in seen_teams:
            try:
                _get(f"{api}/orgs/{org}/teams/{slug}", auth)
            except urllib.error.HTTPError as e:
                raise OSError(f"the team could not be read (HTTP {e.code})") from None
            seen_teams.add(team)
        try:
            data = _get(f"{api}/orgs/{org}/teams/{slug}/memberships/{urllib.parse.quote(login, safe='')}", auth)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return False
            raise OSError(f"HTTP {e.code}") from None
        return isinstance(data, dict) and data.get("state") == "active"

    return reviews, member


def _org_at_base(repo: str, path: str, ref: str, token: str, api: str) -> str:
    """The org file's text at the PR's base commit, through the contents API. Raises on any failure."""
    url = f"{api}/repos/{repo}/contents/{urllib.parse.quote(path)}?ref={urllib.parse.quote(ref)}"
    data = _get(url, {"Authorization": f"Bearer {token}"} if token else {})
    if not isinstance(data, dict) or data.get("encoding") != "base64" or not isinstance(data.get("content"), str):
        raise ValueError("the contents API did not return the file")
    return base64.b64decode(data["content"]).decode("utf-8")


def load_gate_org(org_file: str, pr: dict, files: list[dict] | None, *, repo: str, token: str, api: str,
                  workspace: str, tracker_line: str = "Jira") -> tuple[dict, list[str]]:
    """The org file the gates come from, and warnings. Read from the PR's base commit so a PR can't loosen its own
    gates. If that read fails, the checked-out copy is used only when the PR provably leaves the file unchanged."""
    warnings: list[str] = []
    rel = os.path.normpath(org_file.replace("\\", "/")) if org_file else ""
    if not org_file or os.path.isabs(org_file) or org_file.startswith(("/", "\\")) or re.match(r"^[A-Za-z]:", org_file) \
            or rel == "." or rel == ".." or rel.startswith("../"):
        raise OrgError("must be a path inside the repository, relative to its root (no absolute path, no '..'), so "
                       "it can be read at the PR's base commit")
    base_sha = (pr.get("base") or {}).get("sha") or ""
    why = "the PR event has no base commit"
    if base_sha:
        try:
            text = _org_at_base(repo, rel, base_sha, token, api)
        except urllib.error.HTTPError as e:
            why = (f"it does not exist at the base commit {base_sha[:12]}" if e.code == 404
                   else f"reading it at the base commit failed (HTTP {e.code})")
        except (urllib.error.URLError, OSError, ValueError, UnicodeDecodeError) as e:
            why = f"reading it at the base commit failed ({e})"
        else:
            if files is not None and rel in _changed_paths(files):
                warnings.append(f"this PR changes {org_file}; its gates apply from the next PR, this one is held to "
                                "the base commit's")
            return parse_org(text, f"{org_file}@{base_sha[:12]}", tracker_line=tracker_line), warnings
    if files is None:
        raise OrgError(f"{why}, and the PR's files could not be listed to show the PR leaves it unchanged")
    if rel in _changed_paths(files):
        raise OrgError(f"{why}, and this PR changes it: a PR can't set its own merge gates (a maintainer merges "
                       "changes to the org file)")
    path = os.path.join(workspace, rel)
    warnings.append(f"{org_file} was read from the checkout because {why}; the PR does not change it")
    return load_org(path, tracker_line=tracker_line), warnings


def _title_key(pr: dict, key_pattern: str) -> str | None:
    m = re.match(rf"^\s*\[?({key_pattern})\]?[:\s]", pr.get("title") or "")
    return m.group(1) if m else None


def _read(path: str) -> str:
    with open(path, encoding="utf-8") as fh:
        return fh.read()


def _out(name: str) -> str:
    return os.environ.get(f"INPUT_{name}", "").strip()


def main() -> int:
    with open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8") as fh:
        event = json.load(fh)
    pr = event.get("pull_request")
    if not pr:
        print("not a pull_request event; nothing to check")
        return 0
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    api = os.environ.get("GITHUB_API_URL", "https://api.github.com")
    files = _pr_files(repo, pr["number"], _out("GITHUB_TOKEN"), api)
    res = check_pr(pr, files, key_pattern=_out("KEY_PATTERN") or DEFAULT_KEY,
                   tracker_line=_out("TRACKER_LINE") or "Jira",
                   require_docs=_out("REQUIRE_DOCS").lower() != "false",
                   adr_dir=_out("ADR_DIR") or "docs/decisions",
                   exempt_label=_out("EXEMPT_LABEL") or "no-ticket",
                   exempt_authors=tuple(a.strip() for a in (_out("EXEMPT_AUTHORS") or
                                                            "dependabot[bot],renovate[bot]").split(",") if a.strip()))
    tracker_line = _out("TRACKER_LINE") or "Jira"
    allow_unverified = _out("ALLOW_UNVERIFIED").lower() == "true"
    # the work ticket: the title's key, also on an exempt PR (its labels can apply a gate)
    work_key = res.key or _title_key(pr, _out("KEY_PATTERN") or DEFAULT_KEY)
    work_labels: list[str] | None = None if work_key else []  # None: unknown, so label gates apply
    work_issue_type: str | None = None  # None: unknown (or no work ticket), so issue-type gates apply
    # one reader for rule 6 and the gates; None (no credentials, an unknown provider) fails the gates closed
    reader, skipped, provider_error = None, "", ""
    try:
        reader, skipped = tracker.from_inputs(_out)
    except ValueError as e:  # an unknown provider: fail rather than skip, so a typo can't turn rule 6 off
        provider_error = str(e)
        if work_key:
            res.errors.append(f"{e}; the ticket was not checked")
    if work_key and reader:
        try:
            issue = reader.read(work_key)
            work_labels = issue["labels"]
            work_issue_type = issue.get("issue_type")  # None from a provider that doesn't give it
            if res.key and not res.errors:
                res.errors += check_ticket(issue, res.key)
        except tracker.TicketMissing as e:
            if res.key and not res.errors:
                res.errors.append(f"{res.key} could not be read from {reader.label} ({e}): does the ticket exist?")
        except tracker.BlockerUnreadable as e:
            if res.key and not res.errors:
                res.errors.append(f"{res.key}: {e}; whether an open Decision blocks it is unknown")
        except tracker.BadAnswer as e:
            res.errors.append(f"{work_key}: {e}; the ticket was not checked")
        except tracker.TrackerUnreachable as e:
            # a tracker is configured, so the repository asked for the ticket check: fail closed, as the gates do
            msg = f"{reader.label} was not reachable ({e}); the ticket {work_key} itself was not checked"
            if allow_unverified or not res.key:
                res.warnings.append(msg + (" (allow-unverified is set)" if res.key else ""))
            else:
                res.errors.append(msg + f"; re-run the check once {reader.label} answers (or set allow-unverified "
                                  "for a repository that knowingly accepts this)")
    elif res.key and skipped:
        res.warnings.append(f"{skipped}; rule 6 skipped: the ticket's status, execution label and blocking decisions "
                            "were not checked")
    if reader is None and allow_unverified:
        work_labels = []  # issue-type gates still apply: an unread type is unknown, not "no match"

    if not (res.exempt or "").startswith("author"):
        base_sha = (pr.get("base") or {}).get("sha") or ""
        cfg, cwarns = pr_shape.load_config(
            (lambda: _org_at_base(repo, pr_shape.CONFIG_FILE, base_sha, _out("GITHUB_TOKEN"), api)) if base_sha else None,
            files, lambda: _read(os.path.join(os.environ.get("GITHUB_WORKSPACE", "."), pr_shape.CONFIG_FILE)))
        serrs, swarns = pr_shape.check_shape(pr, files, cfg, key=res.key)
        res.errors += serrs
        res.warnings += cwarns + swarns

    receipt_lines: list[str] = []
    if _out("ARTIFACT_RECEIPT"):
        floor = _out("ARTIFACT_MIN_PASS_RATE")
        try:
            min_rate = float(floor) if floor else None
        except ValueError:
            min_rate = None
            res.errors.append(f"artifact-min-pass-rate {floor!r} is not a number from 0 to 1")
        if min_rate is not None and not 0 <= min_rate <= 1:
            res.errors.append(f"artifact-min-pass-rate {floor!r} is not a number from 0 to 1")
            min_rate = None
        rerrs, rwarns, receipt_lines = receipt.check(
            _out("ARTIFACT_RECEIPT"), os.environ.get("GITHUB_WORKSPACE", "."), allow_unverified=allow_unverified,
            changed=_changed_paths(files) if files is not None else None, min_pass_rate=min_rate)
        res.errors += rerrs
        res.warnings += rwarns

    gates: list[Gate] | None = None
    org_file = _out("ORG_FILE")
    if org_file:
        try:
            org, owarns = load_gate_org(org_file, pr, files, repo=repo, token=_out("GITHUB_TOKEN"), api=api,
                                        workspace=os.environ.get("GITHUB_WORKSPACE", "."), tracker_line=tracker_line)
        except OrgError as e:
            res.errors.append(f"org-file {org_file}: {e}; the merge gates were not checked")
        else:
            res.warnings += owarns
            if provider_error and not work_key:  # a typo can't turn the gates off either: fail, as rule 6 does
                res.errors.append(f"{provider_error}; the merge gates' tickets were not read")
            reviews, member = _github_reviews(repo, pr["number"], _out("REVIEW_TOKEN") or _out("GITHUB_TOKEN"), api)
            gates, gerrs, gwarns = check_gates(pr, files, org, key_pattern=_out("KEY_PATTERN") or DEFAULT_KEY,
                                               tickets=reader, tracker_label=tracker.label_for(_out),
                                               work_key=work_key, work_labels=work_labels,
                                               work_issue_type=work_issue_type, allow_unverified=allow_unverified,
                                               reviews=reviews, team_member=member)
            res.errors += gerrs
            res.warnings += gwarns
            if reader is None and any(g.key for g in gates):
                why = provider_error or f"no {tracker.label_for(_out)} credentials given"
                res.warnings.append(f"{why}; the gate tickets' project, type, links and status were not read (only "
                                    "their key prefix was checked)")

    lines = ["## Work-system PR check", ""]
    if res.exempt:
        lines.append(f"Exempt ({res.exempt}).")
    for w in res.warnings:
        print(f"::warning::{w}")
        lines.append(f"- warning: {w}")
    for e in res.errors:
        print(f"::error::{e}")
        lines.append(f"- error: {e}")
    if gates is not None:
        lines += ["", "### Merge gates", ""] + gate_summary(gates)
    lines += receipt_lines
    if not res.errors and not res.exempt:
        lines.append(f"Passes for {res.key}.")
    elif not res.errors and gates:
        lines.append("The merge gates pass.")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 1 if res.errors else 0


if __name__ == "__main__":
    sys.exit(main())
