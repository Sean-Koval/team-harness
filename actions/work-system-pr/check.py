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
6. With Jira credentials: the ticket exists, is not Done or Wont Do, carries an execution label (`exec:`, or the older
   `lane:`), is a work item (not an Epic or a Decision, nor a Task labelled `type:decision`), and no open Decision blocks it.
7. With an org file (`org-file`, schema team-harness.org/v1), read from the PR's base commit so a PR can't loosen its
   own gates: every merge gate whose `when` matches the PR (always, its changed paths, or the labels on the PR or its
   work ticket) needs a `<pr_line>: <KEY>` line naming a ticket in the gate ticket type's project (`pending` or a
   missing line fails, so merge waits on the approval tickets). With Jira credentials, each gate ticket must exist, be
   in that project, have the ticket type's issue type, carry the links the gate names (`work`: an issue link to the
   PR's work ticket; `pr`: a remote link to the PR or its URL in the description) and, when the gate sets
   `approved_statuses`, be in one of them. The check fails closed: a gate with `approved_statuses` whose ticket can't
   be read (no credentials, Jira down, an SSO page instead of JSON) fails, unless `allow-unverified` is set. An org
   file marked `placeholder: true` is not enforced (a warning says so).

Exempt: PRs with the exemption label (default `no-ticket`) and PRs by the exempt authors (default the dependency
bots) skip rules 1-6; the org's gates (rule 7) still hold, since an exemption is about the ticket, not the approvals.
Reads the event payload, the PR's file list through the GitHub API, the org file, and Jira only with GET; writes
nothing except the job summary.
"""

from __future__ import annotations

import base64
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

DEFAULT_KEY = r"[A-Z][A-Z0-9]{1,9}-[0-9]+"
DONE_CATEGORIES = {"done"}
NOT_WORK_TYPES = {"epic", "decision"}
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


def check_ticket(issue: dict, blockers: list[dict], key: str) -> list[str]:
    """Rule 6, from Jira's issue JSON and the issues that block it."""
    errs = []
    f = issue.get("fields") or {}
    cat = ((f.get("status") or {}).get("statusCategory") or {}).get("key")
    status = (f.get("status") or {}).get("name")
    if cat in DONE_CATEGORIES:
        errs.append(f"{key} is {status}: reopen it or file a new ticket")
    itype = ((f.get("issuetype") or {}).get("name") or "").lower()
    if itype in NOT_WORK_TYPES:
        errs.append(f"{key} is a {itype}; a PR implements a story, task or bug (use 'Decision: {key}' for a decision)")
    labels = [str(lab) for lab in f.get("labels") or []]
    if itype not in NOT_WORK_TYPES and "type:decision" in labels:
        errs.append(f"{key} is a decision (type:decision); a PR implements a story, task or bug "
                    f"(use 'Decision: {key}' for a decision)")
    if not any(lab.startswith(EXEC_PREFIXES) for lab in labels):
        errs.append(f"{key} has no execution label (exec:agent, exec:pair or exec:human; lane:* is still accepted)")
    for b in blockers:
        bf = b.get("fields") or {}
        is_decision = ((bf.get("issuetype") or {}).get("name") or "").lower() == "decision" or \
            "type:decision" in [str(lab) for lab in bf.get("labels") or []]
        if is_decision and \
                ((bf.get("status") or {}).get("statusCategory") or {}).get("key") not in DONE_CATEGORIES:
            errs.append(f"{key} is blocked by open Decision {b.get('key')}: answer it before merging")
    return errs


# --- rule 7: the org's merge gates -----------------------------------------------------------------------------------

ORG_SCHEMA = "team-harness.org/v1"
ORG_KEYS = {"schema", "name", "placeholder", "params", "ticket_types", "gates", "review_request"}
TICKET_TYPE_KEYS = {"id", "project", "issue_type", "role", "summary"}
GATE_KEYS = {"id", "ticket", "when", "pr_line", "links", "filed_by", "approved_statuses"}
WHEN_KEYS = {"paths", "labels"}
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
    _unknown(data, ORG_KEYS, "the org file")
    if data.get("schema") != ORG_SCHEMA:
        raise OrgError(f"schema must be {ORG_SCHEMA!r} (got {data.get('schema')!r})")
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
    gates = data.get("gates")
    if not isinstance(gates, list) or not gates:
        raise OrgError("gates must list at least one gate")
    seen_ids: set[str] = set()
    seen_lines: set[str] = set()
    for i, g in enumerate(gates):
        where = f"gates[{i}]"
        if not isinstance(g, dict):
            raise OrgError(f"{where} must be a mapping")
        _unknown(g, GATE_KEYS, where)
        for k in ("id", "ticket", "pr_line", "filed_by"):
            if not isinstance(g.get(k), str) or not g[k].strip():
                raise OrgError(f"{where} needs a non-empty {k!r}")
        where = f"gate {g['id']!r}"
        if g["id"] in seen_ids:
            raise OrgError(f"gate id {g['id']!r} is used twice")
        if g["pr_line"].lower() in seen_lines:
            raise OrgError(f"pr_line {g['pr_line']!r} is used by two gates")
        if not re.fullmatch(r"[A-Za-z][A-Za-z0-9 _-]*", g["pr_line"]):
            raise OrgError(f"{where} pr_line {g['pr_line']!r} must be a plain name, like 'SRE'")
        if g["pr_line"].lower() in reserved:
            raise OrgError(f"{where} pr_line {g['pr_line']!r} is one of the PR check's own lines")
        seen_ids.add(g["id"])
        seen_lines.add(g["pr_line"].lower())
        t = by_id.get(g["ticket"])
        if t is None:
            raise OrgError(f"{where} names unknown ticket type {g['ticket']!r}")
        if t["role"] != "approval":
            raise OrgError(f"{where} uses ticket type {g['ticket']!r}, which is role {t['role']!r}, not 'approval'")
        if "when" not in g:
            raise OrgError(f"{where} needs a 'when' (always, {{paths: [...]}} or {{labels: [...]}})")
        when = g["when"]
        if when != "always":
            if not isinstance(when, dict) or not when:
                raise OrgError(f"{where} when must be 'always', {{paths: [...]}} or {{labels: [...]}}")
            _unknown(when, WHEN_KEYS, f"{where} when")
            for k in when:
                _str_list(when[k], f"{where} when.{k}")
        if "links" in g:
            bad = [x for x in _str_list(g["links"], f"{where} links") if x not in LINK_KINDS]
            if bad:
                raise OrgError(f"{where} links has {', '.join(bad)} (allowed: {', '.join(sorted(LINK_KINDS))})")
        if g["filed_by"] not in FILED_BY:
            raise OrgError(f"{where} filed_by must be agent or person (got {g.get('filed_by')!r})")
        if "approved_statuses" in g:
            _str_list(g["approved_statuses"], f"{where} approved_statuses")
    return data


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
    #                      | not enforced
    errors: list[str] = field(default_factory=list)


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
             work_labels: Iterable[str] | None = ()) -> tuple[bool, str]:
    """Labels compare case-insensitively and come from the PR and its work ticket. `files` or `work_labels` None means
    they could not be read, and the gate then applies (fail closed)."""
    if when == "always" or when is None:
        return True, "always"
    assert isinstance(when, dict)
    hits = []
    if "labels" in when:
        want = {lab.lower() for lab in when["labels"]}
        hits += [f"label {lab}" for lab in sorted(labels) if lab and lab.lower() in want]
        if work_labels is None:
            if not hits:
                return True, "labels (the work ticket's labels could not be read, so the gate applies)"
        else:
            hits += [f"work ticket label {lab}" for lab in sorted(set(work_labels)) if lab.lower() in want]
    if "paths" in when:
        if files is None:
            return True, "paths (the PR's files could not be listed, so the gate applies)"
        paths = _changed_paths(files)
        hits += [f"path {p}" for p in paths if any(path_matches(p, g) for g in when["paths"])][:3]
    return (True, ", ".join(hits)) if hits else (False, "no matching " + " or ".join(sorted(when)))


def _no_comments(body: str) -> str:
    # an unclosed `<!--` hides the rest of the body when GitHub renders it, so it hides it from the check too
    return re.sub(r"(?s)<!--.*?(?:-->|\Z)", "", body or "")


@dataclass
class GateContext:
    """What the Jira side of rule 7 needs. `fetch(key)` returns an issue's JSON (status, project, issuetype,
    issuelinks, description); `remote_links(key)` its remote links. Both are GETs."""
    fetch: Callable[[str], object] | None = None
    remote_links: Callable[[str], object] | None = None
    work_key: str | None = None
    pr_url: str = ""
    allow_unverified: bool = False


def check_gates(pr: dict, files: list[dict] | None, org: dict, *, key_pattern: str = DEFAULT_KEY,
                fetch: Callable[[str], object] | None = None, remote_links: Callable[[str], object] | None = None,
                work_key: str | None = None, work_labels: Iterable[str] | None = (),
                allow_unverified: bool = False) -> tuple[list[Gate], list[str], list[str]]:
    """Rule 7. Returns the gates with their state, errors and warnings. Fails closed: a gate whose approval can't be
    verified fails unless `allow_unverified` is set."""
    errors: list[str] = []
    warnings: list[str] = []
    ctx = GateContext(fetch, remote_links, work_key, str(pr.get("html_url") or ""), allow_unverified)
    types = {t["id"]: t for t in org["ticket_types"]}
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
        t = types[g["ticket"]]
        applies, why = _applies(g.get("when", "always"), labels, files, work_labels)
        gate = Gate(g["id"], g["pr_line"], t["id"], t["project"], t["issue_type"], g.get("filed_by", "agent"),
                    applies, why)
        gates.append(gate)
        if not applies:
            gate.state = "not required"
            continue
        if placeholder:
            gate.state = "not enforced"
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
            elif ctx.fetch is None:
                if g.get("approved_statuses"):
                    _unverified(gate, "there are no Jira credentials to read it (fork and bot PRs get no secrets)",
                                g["approved_statuses"], ctx, errors=gate.errors, warnings=warnings)
            else:
                _check_gate_ticket(gate, g, t, ctx, warnings)
                if not gate.errors and gate.state == "linked":
                    gate.state = "checked"
        errors += gate.errors
    return gates, errors, warnings


def _unverified(gate: Gate, why: str, approved: list[str], ctx: GateContext, *, errors: list[str],
                warnings: list[str]) -> None:
    """A gate that must be approved but whose ticket couldn't be read: fail, unless allow-unverified is set."""
    msg = (f"gate {gate.id!r}: {gate.key} could not be verified as {' or '.join(approved)} because {why}")
    if ctx.allow_unverified:
        warnings.append(f"{msg}; passing it unverified because allow-unverified is set")
    else:
        gate.state = "unverified"
        errors.append(f"{msg}; the PR can't merge until the check reads it (re-run the check, or set "
                      "allow-unverified for repositories that knowingly accept this)")


def _mentions(obj: object, url: str) -> bool:
    """Whether the JSON (a description or remote links) names this URL itself: `/pull/7` is not `/pull/70`."""
    url = url.rstrip("/")
    return bool(url) and re.search(re.escape(url) + r"(?![\w-])", json.dumps(obj or "")) is not None


def _linked_keys(fields: dict) -> set[str]:
    out = set()
    for link in fields.get("issuelinks") or []:
        if not isinstance(link, dict):
            continue
        for side in ("inwardIssue", "outwardIssue"):
            k = (link.get(side) or {}).get("key")
            if k:
                out.add(str(k))
    return out


def _check_gate_ticket(gate: Gate, g: dict, t: dict, ctx: GateContext, warnings: list[str]) -> None:
    approved: list[str] | None = g.get("approved_statuses")
    assert ctx.fetch is not None

    def unreadable(why: str) -> None:
        if approved:
            _unverified(gate, why, approved, ctx, errors=gate.errors, warnings=warnings)
        else:
            warnings.append(f"gate {gate.id!r}: {gate.key} was not checked because {why}")

    try:
        issue = ctx.fetch(gate.key or "")
    except urllib.error.HTTPError as e:
        gate.state = "invalid"
        gate.errors.append(f"gate {gate.id!r}: {gate.key} could not be read from Jira (HTTP {e.code}): "
                           "does the ticket exist, and can the check's account browse its project?")
        return
    except (urllib.error.URLError, OSError, ValueError) as e:  # ValueError: not JSON, such as an SSO login page
        unreadable(f"Jira did not answer with the ticket ({e})")
        return
    if not isinstance(issue, dict) or not isinstance(issue.get("fields"), dict):
        unreadable("Jira's answer was not an issue")
        return
    f = issue["fields"]
    errs = []
    project = (f.get("project") or {}).get("key") or str(issue.get("key") or "").rsplit("-", 1)[0]
    if project != gate.project:
        gate.state = "invalid"
        errs.append(f"gate {gate.id!r}: {gate.key} is in {project or 'an unknown project'}, not {gate.project}, "
                    f"where the {gate.ticket} ticket is filed")
    itype = (f.get("issuetype") or {}).get("name") or ""
    if itype.lower() != t["issue_type"].lower():
        gate.state = "invalid"
        errs.append(f"gate {gate.id!r}: {gate.key} is a {itype or 'ticket without an issue type'}, not a "
                    f"{t['issue_type']}; file a {t['issue_type']} ({gate.ticket}) for this PR")
    links = g.get("links") or []
    if "work" in links:
        if not ctx.work_key:
            gate.state = "invalid"
            errs.append(f"gate {gate.id!r}: the PR names no work ticket, so {gate.key}'s link to it can't be "
                        "checked; put the work key in the title")
        elif ctx.work_key not in _linked_keys(f):
            gate.state = "invalid"
            errs.append(f"gate {gate.id!r}: {gate.key} has no issue link to the work ticket {ctx.work_key}; link it "
                        f"('relates to') so the approval is for this work")
    if "pr" in links and not _mentions(f.get("description"), ctx.pr_url):
        found = False
        if ctx.pr_url and ctx.remote_links is not None:
            try:
                found = _mentions(ctx.remote_links(gate.key or ""), ctx.pr_url)
            except (urllib.error.URLError, OSError, ValueError) as e:
                unreadable(f"its remote links could not be read ({e})")
                found = True  # reported above
        if not found:
            gate.state = "invalid"
            errs.append(f"gate {gate.id!r}: {gate.key} does not link this PR; add {ctx.pr_url or 'the PR URL'} as a "
                        "remote link or in its description")
    status = (f.get("status") or {}).get("name") or ""
    if approved and status.lower() not in {s.lower() for s in approved}:
        if gate.state == "linked":
            gate.state = "not approved"
        errs.append(f"gate {gate.id!r}: {gate.key} is {status or 'without a status'}; it must be "
                    f"{' or '.join(approved)} before the PR merges")
    gate.errors += errs


def gate_summary(gates: list[Gate]) -> list[str]:
    if not gates:
        return ["The org file declares no merge gates."]
    rows = ["| Gate | Line | Ticket | Applies | State |", "| --- | --- | --- | --- | --- |"]
    for g in gates:
        line = f"`{g.pr_line}: {g.key}`" if g.key else f"`{g.pr_line}:`"
        who = " (a person files it)" if g.filed_by == "person" else ""
        applies = ("yes: " if g.applies else "no: ") + g.why
        rows.append(f"| {g.id} | {line} | {g.issue_type} in {g.project}{who} | {applies.replace('|', '/')} "
                    f"| {g.state} |")
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


def _jira(base: str, user: str, token: str, key: str) -> tuple[dict, list[dict]]:
    auth = {"Authorization": "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()}
    q = urllib.parse.quote(key)
    issue = _get(f"{base.rstrip('/')}/rest/api/3/issue/{q}?fields=status,labels,issuetype,issuelinks", auth)
    blockers = []
    for link in (issue.get("fields") or {}).get("issuelinks") or []:  # type: ignore[union-attr]
        if (link.get("type") or {}).get("name") == "Blocks" and link.get("inwardIssue"):
            blockers.append(link["inwardIssue"])  # "is blocked by": the inward issue blocks this one
    for i, b in enumerate(blockers):
        # link summaries carry no labels; a Decision filed as a Task (`type:decision`) needs one more GET
        if ((b.get("fields") or {}).get("issuetype") or {}).get("name", "").lower() != "decision" and b.get("key"):
            full = _get(f"{base.rstrip('/')}/rest/api/3/issue/{urllib.parse.quote(b['key'])}"
                        "?fields=status,labels,issuetype", auth)
            if isinstance(full, dict):
                blockers[i] = {**full, "key": b["key"]}
    return issue, blockers  # type: ignore[return-value]


def _jira_fetcher(base: str, user: str, token: str) -> tuple[Callable[[str], object], Callable[[str], object]]:
    """(fetch the issue, fetch its remote links) for the gate tickets; GET only."""
    auth = {"Authorization": "Basic " + base64.b64encode(f"{user}:{token}".encode()).decode()}
    root = f"{base.rstrip('/')}/rest/api/3/issue/"
    return (lambda key: _get(f"{root}{urllib.parse.quote(key)}?fields=status,project,issuetype,issuelinks,description",
                             auth),
            lambda key: _get(f"{root}{urllib.parse.quote(key)}/remotelink", auth))


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
    base, user, token = _out("JIRA_BASE_URL"), _out("JIRA_USER"), _out("JIRA_TOKEN")
    creds = bool(base and user and token)
    allow_unverified = _out("ALLOW_UNVERIFIED").lower() == "true"
    # the work ticket: the title's key, also on an exempt PR (its labels can apply a gate)
    work_key = res.key or _title_key(pr, _out("KEY_PATTERN") or DEFAULT_KEY)
    work_labels: list[str] | None = None if work_key else []  # None: unknown, so label gates apply
    if work_key and creds:
        try:
            issue, blockers = _jira(base, user, token, work_key)
            if not isinstance(issue, dict):
                raise TypeError("Jira's answer was not an issue")
            work_labels = [str(lab) for lab in (issue.get("fields") or {}).get("labels") or []]
            if res.key and not res.errors:
                res.errors += check_ticket(issue, blockers, res.key)
        except urllib.error.HTTPError as e:
            if res.key and not res.errors:
                res.errors.append(f"{res.key} could not be read from Jira (HTTP {e.code}): does the ticket exist?")
        except (urllib.error.URLError, OSError, ValueError, TypeError) as e:
            res.warnings.append(f"Jira was not reachable ({e}); the ticket {work_key} itself was not checked")
    elif res.key:
        res.warnings.append("no Jira credentials given; the ticket's status, execution label and blocking decisions were not checked")
    if not creds and allow_unverified:
        work_labels = []

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
            fetch, remote = _jira_fetcher(base, user, token) if creds else (None, None)
            gates, gerrs, gwarns = check_gates(pr, files, org, key_pattern=_out("KEY_PATTERN") or DEFAULT_KEY,
                                               fetch=fetch, remote_links=remote,
                                               work_key=work_key,
                                               work_labels=work_labels, allow_unverified=allow_unverified)
            res.errors += gerrs
            res.warnings += gwarns
            if fetch is None and any(g.key for g in gates):
                res.warnings.append("no Jira credentials given; the gate tickets' project, type, links and status "
                                    "were not read (only their key prefix was checked)")

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
