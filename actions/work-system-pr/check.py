#!/usr/bin/env python3
"""The work-system PR check: every pull request names its ticket, says where its docs went, and (optionally) points
at a ticket that is open, laned and not waiting on a decision.

Every surface (hangar jobs, local Claude Code or Codex, cloud sessions, a person in the browser) ends in a pull request,
so this is the one place the rules hold for all of them. The session hook (shared/work-system) only catches them
earlier. Rules:

1. The title starts with a ticket key (`KAN-315: ...`).
2. The body has `<tracker line>: <KEY>` (default `Jira: KAN-315`) for the same key.
3. The body has a non-empty `Docs:` line; `none needed` must give a reason.
4. If the body says `Decision: <KEY>`, the PR adds or changes a file under the ADR directory that mentions that key.
5. The branch should contain the key (a warning only: cloud sessions are assigned branch names).
6. With Jira credentials: the ticket exists, is not Done or Wont Do, carries a `lane:` label, is a work item (not an
   Epic or a Decision), and no open Decision blocks it.

Exempt: PRs with the exemption label (default `no-ticket`) and PRs by the exempt authors (default the dependency
bots). Reads the event payload, the PR's file list through the GitHub API, and Jira only with GET; writes nothing
except the job summary.
"""

from __future__ import annotations

import base64
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field

DEFAULT_KEY = r"[A-Z][A-Z0-9]{1,9}-[0-9]+"
DONE_CATEGORIES = {"done"}
NOT_WORK_TYPES = {"epic", "decision"}


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
    if not any(str(lab).startswith("lane:") for lab in f.get("labels") or []):
        errs.append(f"{key} has no lane: label (lane:agent, lane:pair or lane:human)")
    for b in blockers:
        bf = b.get("fields") or {}
        if ((bf.get("issuetype") or {}).get("name") or "").lower() == "decision" and \
                ((bf.get("status") or {}).get("statusCategory") or {}).get("key") not in DONE_CATEGORIES:
            errs.append(f"{key} is blocked by open Decision {b.get('key')}: answer it before merging")
    return errs


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
    return issue, blockers  # type: ignore[return-value]


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
    files = _pr_files(repo, pr["number"], _out("GITHUB_TOKEN"), os.environ.get("GITHUB_API_URL",
                                                                               "https://api.github.com"))
    res = check_pr(pr, files, key_pattern=_out("KEY_PATTERN") or DEFAULT_KEY,
                   tracker_line=_out("TRACKER_LINE") or "Jira",
                   require_docs=_out("REQUIRE_DOCS").lower() != "false",
                   adr_dir=_out("ADR_DIR") or "docs/decisions",
                   exempt_label=_out("EXEMPT_LABEL") or "no-ticket",
                   exempt_authors=tuple(a.strip() for a in (_out("EXEMPT_AUTHORS") or
                                                            "dependabot[bot],renovate[bot]").split(",") if a.strip()))
    base, user, token = _out("JIRA_BASE_URL"), _out("JIRA_USER"), _out("JIRA_TOKEN")
    if res.key and not res.errors and base and user and token:
        try:
            issue, blockers = _jira(base, user, token, res.key)
            res.errors += check_ticket(issue, blockers, res.key)
        except urllib.error.HTTPError as e:
            res.errors.append(f"{res.key} could not be read from Jira (HTTP {e.code}): does the ticket exist?")
        except (urllib.error.URLError, OSError, ValueError) as e:
            res.warnings.append(f"Jira was not reachable ({e}); the ticket itself was not checked")
    elif res.key and not (base and user and token):
        res.warnings.append("no Jira credentials given; the ticket's status, lane and blocking decisions were not checked")

    lines = ["## Work-system PR check", ""]
    if res.exempt:
        lines.append(f"Exempt ({res.exempt}).")
    for w in res.warnings:
        print(f"::warning::{w}")
        lines.append(f"- warning: {w}")
    for e in res.errors:
        print(f"::error::{e}")
        lines.append(f"- error: {e}")
    if not res.errors and not res.exempt:
        lines.append(f"Passes for {res.key}.")
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 1 if res.errors else 0


if __name__ == "__main__":
    sys.exit(main())
