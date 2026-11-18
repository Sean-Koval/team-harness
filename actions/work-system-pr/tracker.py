"""The tracker role, as the work-system PR check reads it (KAN-437).

check.py asks one question of the tracker: what is this ticket now? It gets the answer as a normalised issue and never
sees the tracker's own JSON, so changing trackers means adding a provider here, not editing check.py. The shape
follows ai-dlc's tracker role (`tracker_get`: a state and labels) and adds what rule 6 needs and that role does not
return yet: the ticket's kind and the issues that block it.

A normalised issue is a dict:

    key        the ticket key, e.g. "KAN-315"
    status     the status as people see it, e.g. "In Progress" (for messages only)
    category   "todo", "in_progress" or "done": done covers every finished status (Done, Wont Do, Cancelled)
    kind       "work", "epic" or "decision"
    labels     list of str
    blocked_by list of {key, category, kind, labels}: the issues that block this one
    issue_type optional: the ticket's issue type as the tracker names it, e.g. "Story" (for the org's
               `when: issue_types` gates); None when the provider doesn't give it, and those gates then apply

`read(key)` raises `TicketMissing` when the tracker answered that it has no such ticket (or refused to show it),
`BlockerUnreadable` when an issue that blocks it can't be read, and `TrackerUnreachable` when the tracker could not
be asked or its answer was not an issue. A provider's answer passes `normalised()` before check.py sees it; one that
isn't a normalised issue raises `BadAnswer`, which fails the check rather than passing an unjudged ticket.

Providers are built in by name, never loaded from the repository: the check runs on a PR's own checkout, and a PR must
not be able to bring its own tracker. Credentials are named by the action's inputs and passed in from secrets; nothing
here stores a value. Reads only (GET).
"""

from __future__ import annotations

import base64
import http.client
import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any

CATEGORIES = ("todo", "in_progress", "done")
KINDS = ("work", "epic", "decision")
DEFAULT_PROVIDER = "jira-cloud"


class TicketMissing(Exception):
    """The tracker answered: there is no such ticket, or it isn't visible to these credentials."""


class TrackerUnreachable(Exception):
    """The tracker could not be asked, or did not answer with an issue."""


class BlockerUnreadable(Exception):
    """An issue that blocks the ticket could not be read, so whether it is an open Decision is unknown."""


class BadAnswer(Exception):
    """A provider's answer is not a normalised issue (a provider bug): the ticket can't be judged from it."""


def _labels(v: object, where: str) -> list[str]:
    if not isinstance(v, list) or not all(isinstance(x, str) for x in v):
        raise BadAnswer(f"{where}: labels must be a list of strings")
    return list(v)


def _ref(d: object, where: str) -> dict[str, Any]:
    if not isinstance(d, dict):
        raise BadAnswer(f"{where} is not an issue")
    key, cat, kind = d.get("key"), d.get("category"), d.get("kind")
    if not isinstance(key, str) or not key:
        raise BadAnswer(f"{where} has no key")
    if cat not in CATEGORIES:
        raise BadAnswer(f"{where}: category {cat!r} is not one of {', '.join(CATEGORIES)}")
    if kind not in KINDS:
        raise BadAnswer(f"{where}: kind {kind!r} is not one of {', '.join(KINDS)}")
    if "labels" not in d:  # required: a missing list would hide a `type:decision` label
        raise BadAnswer(f"{where} has no labels (an empty list is fine)")
    return {"key": key, "category": cat, "kind": kind, "labels": _labels(d["labels"], where)}


def normalised(issue: object, key: str) -> dict[str, Any]:
    """`issue` checked against the normalised shape and copied; raises BadAnswer when it isn't one."""
    out = _ref(issue, f"the tracker's answer for {key}")
    if out["key"] != key:
        raise BadAnswer(f"the tracker answered for {out['key']}, not {key}")
    status = issue.get("status")  # type: ignore[union-attr]
    out["status"] = status if isinstance(status, str) and status else out["category"].replace("_", " ")
    if "blocked_by" not in issue:  # type: ignore[operator]  # required: missing must not read as "nothing blocks it"
        raise BadAnswer(f"the tracker's answer for {key} has no blocked_by (an empty list is fine)")
    blocked = issue["blocked_by"]  # type: ignore[index]
    if not isinstance(blocked, list):
        raise BadAnswer(f"the tracker's answer for {key}: blocked_by must be a list")
    out["blocked_by"] = [_ref(b, f"an issue blocking {key}") for b in blocked]
    itype = issue.get("issue_type")  # type: ignore[union-attr]
    if itype is not None and not isinstance(itype, str):
        raise BadAnswer(f"the tracker's answer for {key}: issue_type must be a string")
    out["issue_type"] = itype or None
    return out


# --- jira-cloud: Jira Cloud's REST API v3, Basic auth with a scoped API token ---------------------------------------

_JIRA_CATEGORY = {"new": "todo", "indeterminate": "in_progress", "done": "done"}


def _dict(v: object) -> Mapping[str, Any]:
    return v if isinstance(v, dict) else {}


def _jira_kind(fields: Mapping[str, Any]) -> str:
    name = str(_dict(fields.get("issuetype")).get("name") or "").lower()
    return name if name in ("epic", "decision") else "work"


def _jira_category(fields: Mapping[str, Any]) -> str:
    # an unknown category is open: only Jira's own "done" category finishes a ticket
    return _JIRA_CATEGORY.get(str(_dict(_dict(fields.get("status")).get("statusCategory")).get("key")), "in_progress")


def _jira_labels(fields: Mapping[str, Any]) -> list[str]:
    labels = fields.get("labels") or []
    return [str(x) for x in labels] if isinstance(labels, list) else []


class JiraCloud:
    """Reads a ticket and the issues that block it ("is blocked by" links of type Blocks)."""

    label = "Jira"
    inputs = ("JIRA_BASE_URL", "JIRA_USER", "JIRA_TOKEN")

    def __init__(self, config: Mapping[str, str], get: Callable[[str, dict[str, str]], object] | None = None):
        self.base = config["JIRA_BASE_URL"].rstrip("/")
        token = base64.b64encode(f"{config['JIRA_USER']}:{config['JIRA_TOKEN']}".encode()).decode()
        self.auth = {"Authorization": "Basic " + token}
        self._get = get or _get

    def _issue(self, key: str, fields: str) -> dict[str, Any]:
        try:
            data = self._get(f"{self.base}/rest/api/3/issue/{urllib.parse.quote(key)}?fields={fields}", self.auth)
        except urllib.error.HTTPError as e:
            raise TicketMissing(f"HTTP {e.code}") from None
        # ValueError: not JSON, such as an SSO login page; HTTPException: a connection cut mid-answer
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            raise TrackerUnreachable(str(e)) from None
        if not isinstance(data, dict) or not isinstance(data.get("fields"), dict):
            raise TrackerUnreachable("the answer was not an issue")
        return data

    def read(self, key: str) -> dict[str, Any]:
        issue = self._issue(key, "status,labels,issuetype,issuelinks")
        f = issue["fields"]
        blocked = []
        links = f.get("issuelinks") or []
        for link in links if isinstance(links, list) else []:
            link = _dict(link)
            b = _dict(link.get("inwardIssue"))
            if _dict(link.get("type")).get("name") != "Blocks" or not isinstance(b.get("key"), str):
                continue  # only "is blocked by": the inward issue of a Blocks link blocks this one
            bf = _dict(b.get("fields"))
            # link summaries carry no labels: a Task labelled type:decision needs a GET of its own
            if _jira_kind(bf) != "decision":
                try:
                    bf = self._issue(b["key"], "status,labels,issuetype")["fields"]
                except (TicketMissing, TrackerUnreachable) as e:  # fails the ticket, never passes it
                    raise BlockerUnreadable(f"{b['key']} blocks it and could not be read ({e})") from None
            blocked.append({"key": b["key"], "category": _jira_category(bf), "kind": _jira_kind(bf),
                            "labels": _jira_labels(bf)})
        # the key asked for: Jira answers a moved ticket's old key with its new one, and the PR names the old one
        return {"key": key, "status": str(_dict(f.get("status")).get("name") or ""),
                "category": _jira_category(f), "kind": _jira_kind(f),
                "labels": _jira_labels(f), "blocked_by": blocked,
                "issue_type": str(_dict(f.get("issuetype")).get("name") or "") or None}


def _get(url: str, headers: dict[str, str]) -> object:
    req = urllib.request.Request(url, headers={"Accept": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=20) as resp:  # GET only
        return json.load(resp)


PROVIDERS: dict[str, type] = {"jira-cloud": JiraCloud}


class Reader:
    """`read(key)` through one provider, its answer checked against the normalised shape."""

    def __init__(self, name: str, provider: Any):
        self.name, self.label, self._provider = name, getattr(provider, "label", name), provider

    def read(self, key: str) -> dict[str, Any]:
        try:
            answer = self._provider.read(key)
        except (TicketMissing, TrackerUnreachable, BlockerUnreadable):
            raise
        except Exception as e:  # noqa: BLE001 - a provider bug fails the check (BadAnswer), never passes it
            raise BadAnswer(f"the {self.name} provider failed: {type(e).__name__}: {e}") from None
        return normalised(answer, key)


def from_inputs(get_input: Callable[[str], str]) -> tuple[Reader | None, str]:
    """(a reader, "") when the selected provider has every input it needs; else (None, why rule 6 is skipped).
    Raises ValueError for a provider name that isn't built in."""
    name = get_input("TRACKER_PROVIDER") or DEFAULT_PROVIDER
    cls = PROVIDERS.get(name)
    if cls is None:
        raise ValueError(f"tracker-provider {name!r} is not one of: {', '.join(sorted(PROVIDERS))}")
    config = {k: get_input(k) for k in cls.inputs}
    missing = [k for k, v in config.items() if not v]
    if missing:
        names = ", ".join(k.lower().replace("_", "-") for k in missing)
        return None, f"no tracker credentials given (tracker-provider {name} needs {names})"
    return Reader(name, cls(config)), ""
