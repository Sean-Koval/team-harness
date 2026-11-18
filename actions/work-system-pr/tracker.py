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

Rule 7's approval gates ask a second question, through `gate_issue(key, fields)`: what does this gate ticket show?
Its answer is a normalised gate ticket (KAN-538):

    key        the ticket key
    project    the project (space, team) the ticket is filed in, e.g. "SREPROJ"
    issue_type the ticket's issue type as the tracker names it, e.g. "Change Request"; "" when it has none
    status     the status as people see it, e.g. "Approved"
    links      list of str: the keys of the tickets it links to, either way
    text       str: the ticket's description, as text to search for a URL ("" when it has none)
    field_values {field id: list of str}: the value names of each field asked for that the ticket carries; a field
               the tracker did not return is absent, an empty one is []

and `gate_links(key)` answers the ticket's remote (web) links as text to search for a URL.

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
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from typing import Any

CATEGORIES = ("todo", "in_progress", "done")
# a field id an org's `approved_field` may name: the jira-cloud provider's custom field ids, or a system field's name
FIELD_ID = re.compile(r"^(customfield_[0-9]+|[a-z][A-Za-z0-9]*)$")
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


def gate_normalised(issue: object, key: str) -> dict[str, Any]:
    """A gate ticket checked against the normalised shape and copied; raises BadAnswer when it isn't one."""
    where = f"the tracker's answer for {key}"
    if not isinstance(issue, dict):
        raise BadAnswer(f"{where} is not an issue")
    if issue.get("key") != key:
        raise BadAnswer(f"the tracker answered for {issue.get('key')!r}, not {key}")
    out: dict[str, Any] = {"key": key}
    for name in ("project", "issue_type", "status", "text"):
        if not isinstance(issue.get(name), str):
            raise BadAnswer(f"{where}: {name} must be a string")
        out[name] = issue[name]
    links = issue.get("links")
    if not isinstance(links, list) or not all(isinstance(x, str) for x in links):
        raise BadAnswer(f"{where}: links must be a list of keys")
    values = issue.get("field_values")
    if not isinstance(values, dict) or not all(isinstance(k, str) and isinstance(v, list) and
                                               all(isinstance(x, str) for x in v) for k, v in values.items()):
        raise BadAnswer(f"{where}: field_values must map each field id to a list of value names")
    out["links"], out["field_values"] = list(links), {k: list(v) for k, v in values.items()}
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


def _jira_values(v: object) -> list[str]:
    """A Jira field's value as names: a select option's value, a user's or version's name, a string or a number; a
    list gives each of its values."""
    if isinstance(v, list):
        return [x for item in v for x in _jira_values(item)]
    if isinstance(v, dict):
        for k in ("value", "name", "displayName"):
            if isinstance(v.get(k), str):
                return [v[k]]
        return []
    if isinstance(v, (str, int, float)) and not isinstance(v, bool):
        return [str(v)]
    return []


def _jira_text(v: object) -> str:
    """A description (Atlassian Document Format, or a plain string) as text to search for a URL."""
    return v if isinstance(v, str) else json.dumps(v) if v else ""


def jira_gate_issue(issue: object, key: str, fields: Iterable[str]) -> dict[str, Any]:
    """Jira's answer for a gate ticket as a normalised gate ticket (the provider's mapping, kept apart from its HTTP
    so a caller holding Jira's answers can use it). Raises TrackerUnreachable when the answer is not an issue."""
    if not isinstance(issue, dict) or not isinstance(issue.get("fields"), dict):
        raise TrackerUnreachable("the answer was not an issue")
    f = issue["fields"]
    links = []
    for link in f.get("issuelinks") or []:
        for side in ("inwardIssue", "outwardIssue"):
            k = _dict(_dict(link).get(side)).get("key")
            if k:
                links.append(str(k))
    return {"key": key, "links": links, "text": _jira_text(f.get("description")),
            "project": str(_dict(f.get("project")).get("key") or str(issue.get("key") or "").rsplit("-", 1)[0]),
            "issue_type": str(_dict(f.get("issuetype")).get("name") or ""),
            "status": str(_dict(f.get("status")).get("name") or ""),
            "field_values": {name: _jira_values(f[name]) for name in fields if name in f}}


class JiraAnswers:
    """The jira-cloud gate mapping over answers a caller already holds: `fetch(key)` returns Jira's issue JSON and
    `remote_links(key)` its remote links; an HTTPError from `fetch` is a missing ticket."""

    label = "Jira"

    def __init__(self, fetch: Callable[[str], object], remote_links: Callable[[str], object] | None = None):
        self._fetch, self._remote = fetch, remote_links

    def gate_issue(self, key: str, fields: Iterable[str] = ()) -> dict[str, Any]:
        fields = list(fields)
        try:
            return jira_gate_issue(self._fetch(key), key, fields)
        except urllib.error.HTTPError as e:
            raise TicketMissing(f"HTTP {e.code}") from None
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            raise TrackerUnreachable(str(e)) from None

    def gate_links(self, key: str) -> str:
        if self._remote is None:
            return ""
        try:
            return json.dumps(self._remote(key) or "")
        except (urllib.error.URLError, http.client.HTTPException, OSError, ValueError) as e:
            raise TrackerUnreachable(str(e)) from None


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

    def _gate_answers(self, fields: Iterable[str]) -> JiraAnswers:
        root = f"{self.base}/rest/api/3/issue/"
        want = ",".join(["status", "project", "issuetype", "issuelinks", "description", *sorted(set(fields))])
        return JiraAnswers(lambda key: self._get(f"{root}{urllib.parse.quote(key)}?fields={want}", self.auth),
                           lambda key: self._get(f"{root}{urllib.parse.quote(key)}/remotelink", self.auth))

    def gate_issue(self, key: str, fields: Iterable[str] = ()) -> dict[str, Any]:
        """A gate ticket: project, issue type, status, links, description and the org's approved_field ids."""
        fields = list(fields)
        return self._gate_answers(fields).gate_issue(key, fields)

    def gate_links(self, key: str) -> str:
        return self._gate_answers(()).gate_links(key)

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

    def gate_issue(self, key: str, fields: Iterable[str] = ()) -> dict[str, Any]:
        return gate_reader(self._provider, self.name).gate_issue(key, fields)

    def gate_links(self, key: str) -> str:
        return gate_reader(self._provider, self.name).gate_links(key)


class GateReader:
    """`gate_issue` and `gate_links` through one provider, answers checked against the normalised gate shape. A
    provider that raises anything but the tracker's own exceptions fails the gate (BadAnswer), never passes it."""

    def __init__(self, provider: Any, name: str = ""):
        self.name = name or getattr(provider, "label", "tracker")
        self.label, self._provider = getattr(provider, "label", self.name), provider

    def gate_issue(self, key: str, fields: Iterable[str] = ()) -> dict[str, Any]:
        try:
            answer = self._provider.gate_issue(key, list(fields))
        except (TicketMissing, TrackerUnreachable, BadAnswer):  # its own words, not wrapped again
            raise
        except Exception as e:  # noqa: BLE001
            raise BadAnswer(f"the {self.name} provider failed: {type(e).__name__}: {e}") from None
        return gate_normalised(answer, key)

    def gate_links(self, key: str) -> str:
        try:
            answer = self._provider.gate_links(key)
        except (TicketMissing, TrackerUnreachable, BadAnswer):  # its own words, not wrapped again
            raise
        except Exception as e:  # noqa: BLE001
            raise BadAnswer(f"the {self.name} provider failed: {type(e).__name__}: {e}") from None
        if not isinstance(answer, str):
            raise BadAnswer(f"the {self.name} provider's remote links for {key} are not text")
        return answer


def gate_reader(provider: Any, name: str = "") -> GateReader:
    return provider if isinstance(provider, GateReader) else GateReader(provider, name)


def label_for(get_input: Callable[[str], str]) -> str:
    """The selected provider's name for its tracker, as messages say it ("Jira"); the provider name when unknown."""
    name = get_input("TRACKER_PROVIDER") or DEFAULT_PROVIDER
    return str(getattr(PROVIDERS.get(name), "label", name))


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
