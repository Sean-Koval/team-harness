#!/usr/bin/env python3
"""Render the shared work-system layer into every harness that carries it, or check that it is in sync.

`shared/work-system/` is the one place the work-system skills and hook are edited. `targets.yaml` names the
harnesses, the pieces each one carries, and each harness's profile (`profiles/<harness>.yaml`). A shared file may hold
`{{name}}` placeholders; the profile's `params` fill them, so nothing person- or company-specific lives in a shared
file and each harness gets concrete text. For each target harness this:

- renders `shared/work-system/skills/<name>/` into `harnesses/<h>/skills/<name>/` (the whole directory), for the
  shared skill list plus the harness's own `skills:` from targets.yaml;
- renders the hook into `harnesses/<h>/native/claude-code/hooks/`;
- deletes any `harnesses/<h>/skills/<name>/` that it does not produce and that the harness does not declare as its
  own (`own_skills:` in targets.yaml), so an org skill that is removed or renamed does not linger and get re-pinned;
- checks that the harness's `native/claude-code/settings.json` registers the hook on PreToolUse for Bash and MCP
  tools (it never edits settings.json: that file is the harness's own).

A harness may also name a company's org overlay (`org: orgs/<org>` in targets.yaml). Its `org.yaml`
(`team-harness.org/v1`) is validated; its `params` may set only `tracker` and the `kb_*` keys, and win over the
profile's for those (the merge rule, the wall and the rest stay the profile's); it fills the generated placeholders
`{{org_status}}`, `{{org_ticket_types}}`, `{{org_gates}}` and `{{org_review_request}}` (markdown); and each of its
`skills/<name>/` (at least `org-process`, the company's own flow skill) is copied into the harness's skills verbatim,
never rendered, so a company document may hold `{{ }}` freely. suite-default never takes an org: that is the
work/home wall.

A placeholder the profile does not fill is an error, never an empty string.

    python scripts/sync_shared.py            # write the copies
    python scripts/sync_shared.py --check    # CI: exit 1 when a copy differs, a skill copy is left over, a
                                             # placeholder is unfilled, the hook is not registered, an org is
                                             # invalid, or suite-default names an org

After a write, re-pin each changed harness (`python scripts/relock.py harnesses/<h> --write`) and re-render its
environments (`python scripts/render_envs.py harnesses/<h>`).
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import string
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SHARED = ROOT / "shared" / "work-system"
PLACEHOLDER = re.compile(r"\{\{\s*([a-z_][a-z0-9_]*)\s*\}\}")

# The work/home wall: these harnesses never carry a company's org overlay.
NO_ORG = frozenset({"suite-default"})
ORG_SCHEMA = "team-harness.org/v1"
ORG_KEYS = {"schema", "name", "placeholder", "params", "ticket_types", "gates", "review_request"}
TICKET_KEYS = {"id", "project", "issue_type", "role", "summary"}
GATE_KEYS = {"id", "ticket", "when", "pr_line", "links", "filed_by", "approved_statuses"}
REVIEW_KEYS = {"room", "template"}
ROLES = {"work", "approval"}
LINKS = {"pr", "work", "repo"}
FILED_BY = {"agent", "person"}
SUMMARY_FIELDS = {"work_key", "pr_title", "pr_url", "repo"}
TEMPLATE_FIELDS = SUMMARY_FIELDS | {"summary", "gate_lines", "risk"}
RESERVED_PR_LINES = {"jira", "docs", "decision"}  # the PR check's own lines
# What an org may override: where tickets and pages go. The merge rule, the wall, the approval steps and the rest are
# the harness profile's, so a company fork cannot turn on merging or drop the wall from org.yaml.
ORG_PARAMS = frozenset({"tracker"})
ORG_PARAM_PREFIXES = ("kb_",)
PR_LINE = re.compile(r"^[A-Za-z][A-Za-z0-9 _-]*$")


def _files(d: Path) -> dict[str, bytes]:
    return {str(p.relative_to(d)): p.read_bytes() for p in sorted(d.rglob("*")) if p.is_file()}


def render(data: bytes, params: dict[str, str], where: str, problems: list[str]) -> bytes:
    """`data` with every {{name}} replaced by params[name]; an unfilled name is recorded in `problems`."""
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return data

    def sub(m: re.Match) -> str:
        name = m.group(1)
        if name not in params:
            hint = " (it needs an org: in targets.yaml)" if name.startswith("org_") else ""
            problems.append(f"{where}: placeholder {{{{{name}}}}} is not in the profile{hint}")
            return m.group(0)
        return str(params[name]).strip()

    return PLACEHOLDER.sub(sub, text).encode("utf-8")


def _profile(shared: Path, h: str, entry: dict, problems: list[str]) -> dict[str, str]:
    path = entry.get("profile")
    if not path:
        problems.append(f"{h}: targets.yaml names no profile")
        return {}
    try:
        return (yaml.safe_load((shared / path).read_text()) or {}).get("params") or {}
    except (OSError, yaml.YAMLError) as e:
        problems.append(f"{h}: cannot read {path}: {e}")
        return {}


def _fields(template: str) -> set[str]:
    """The {field} names in a str.format template; ValueError when it is malformed (an unmatched brace)."""
    return {f for _, f, _, _ in string.Formatter().parse(template) if f}


def _template_problems(where: str, template: str, allowed: set[str]) -> list[str]:
    """Problems with a {field} template: malformed, an unknown field, or a doubled brace (which would reach the
    agent as a literal `{{x}}`)."""
    if "{{" in template or "}}" in template:
        return [f"{where}: doubled braces ({{{{ or }}}}) are not allowed; use {{field}} with one of {sorted(allowed)}"]
    try:
        fields = _fields(template)
    except ValueError as e:
        return [f"{where}: malformed template ({e})"]
    return [f"{where} field {{{f}}} is not one of {sorted(allowed)}" for f in sorted(fields - allowed)]


def _unknown(where: str, d: dict, allowed: set[str], problems: list[str]) -> None:
    for k in sorted(set(d) - allowed):
        problems.append(f"{where}: unknown key {k!r}")


def validate_org(org: object, where: str, profile_keys: set[str] | None = None) -> list[str]:
    """Problems with an org.yaml (team-harness.org/v1); empty when it is valid."""
    problems: list[str] = []
    if not isinstance(org, dict):
        return [f"{where}: not a mapping"]
    _unknown(where, org, ORG_KEYS, problems)
    if org.get("schema") != ORG_SCHEMA:
        problems.append(f"{where}: schema must be {ORG_SCHEMA!r}")
    if not isinstance(org.get("name"), str) or not org.get("name"):
        problems.append(f"{where}: name must be a non-empty string")
    if not isinstance(org.get("placeholder", False), bool):
        problems.append(f"{where}: placeholder must be true or false")

    params = org.get("params") or {}
    if not isinstance(params, dict):
        problems.append(f"{where}: params must be a mapping")
        params = {}
    for k, v in params.items():
        if not isinstance(v, str):
            problems.append(f"{where}: params.{k} must be a string")
        if str(k).startswith("org_"):
            problems.append(f"{where}: params.{k}: org_* placeholders are generated from org.yaml")
        elif k not in ORG_PARAMS and not str(k).startswith(ORG_PARAM_PREFIXES):
            problems.append(f"{where}: params.{k} cannot be set by an org (only tracker and kb_* may be; the merge "
                            f"rule, the wall and the rest stay the harness profile's)")
        elif profile_keys is not None and k not in profile_keys:
            problems.append(f"{where}: params.{k} is not a profile parameter (org params override the profile's)")

    for k in ("ticket_types", "gates"):
        if not isinstance(org.get(k) or [], list):
            problems.append(f"{where}: {k} must be a list")
    types: dict[str, dict] = {}
    for i, t in enumerate(org.get("ticket_types") if isinstance(org.get("ticket_types"), list) else []):
        w = f"{where}: ticket_types[{i}]"
        if not isinstance(t, dict):
            problems.append(f"{w}: not a mapping")
            continue
        _unknown(w, t, TICKET_KEYS, problems)
        for k in ("id", "project", "issue_type", "role"):
            if not isinstance(t.get(k), str) or not t.get(k):
                problems.append(f"{w}: {k} is required (a string)")
        if t.get("role") is not None and t.get("role") not in ROLES:
            problems.append(f"{w}: role must be one of {sorted(ROLES)}")
        if "summary" in t:
            if not isinstance(t["summary"], str):
                problems.append(f"{w}: summary must be a string")
            else:
                errs = _template_problems(f"{w}: summary", t["summary"], SUMMARY_FIELDS)
                problems.extend(errs)
                if not errs and {"work_key", "pr_title"} <= _fields(t["summary"]):
                    problems.append(f"{w}: summary uses both {{work_key}} and {{pr_title}}, but the PR title already "
                                    f"starts with the work key; drop {{work_key}}")
        if isinstance(t.get("id"), str):
            if t["id"] in types:
                problems.append(f"{w}: ticket type id {t['id']!r} is not unique")
            types[t["id"]] = t
    if not types:
        problems.append(f"{where}: ticket_types must list at least one ticket type")

    gate_ids: set[str] = set()
    pr_lines: set[str] = set()
    for i, g in enumerate(org.get("gates") if isinstance(org.get("gates"), list) else []):
        w = f"{where}: gates[{i}]"
        if not isinstance(g, dict):
            problems.append(f"{w}: not a mapping")
            continue
        _unknown(w, g, GATE_KEYS, problems)
        for k in ("id", "ticket", "pr_line", "filed_by"):
            if not isinstance(g.get(k), str) or not g.get(k):
                problems.append(f"{w}: {k} is required (a string)")
        if isinstance(g.get("id"), str):
            if g["id"] in gate_ids:
                problems.append(f"{w}: gate id {g['id']!r} is not unique")
            gate_ids.add(g["id"])
        if isinstance(g.get("pr_line"), str):
            line = g["pr_line"]
            if not PR_LINE.match(line):
                problems.append(f"{w}: pr_line {line!r} must be a word or two (letters, digits, space, - or _)")
            if line.lower() in RESERVED_PR_LINES:
                problems.append(f"{w}: pr_line {line!r} is one of the PR check's own lines")
            if line.lower() in pr_lines:
                problems.append(f"{w}: pr_line {line!r} is not unique")
            pr_lines.add(line.lower())
        ticket = g.get("ticket")
        if isinstance(ticket, str) and ticket:
            if ticket not in types:
                problems.append(f"{w}: ticket {ticket!r} is not a ticket_types id")
            elif types[ticket].get("role") != "approval":
                problems.append(f"{w}: ticket {ticket!r} must have role approval (only approval tickets gate a PR)")
        when = g.get("when")
        if when != "always":
            if not isinstance(when, dict) or not when or set(when) - {"paths", "labels"}:
                problems.append(f"{w}: when must be always, {{paths: [globs]}} or {{labels: [names]}}")
            else:
                for k, v in when.items():
                    if not isinstance(v, list) or not v or not all(isinstance(x, str) and x for x in v):
                        problems.append(f"{w}: when.{k} must be a non-empty list of strings")
        if g.get("filed_by") is not None and g.get("filed_by") not in FILED_BY:
            problems.append(f"{w}: filed_by must be agent or person")
        links = g.get("links", [])
        if not isinstance(links, list) or set(links) - LINKS:
            problems.append(f"{w}: links must be a list of {sorted(LINKS)}")
        statuses = g.get("approved_statuses")
        if statuses is not None and (not isinstance(statuses, list) or not statuses
                                     or not all(isinstance(x, str) and x for x in statuses)):
            problems.append(f"{w}: approved_statuses must be a non-empty list of status names")
    if not gate_ids:
        problems.append(f"{where}: gates must list at least one gate")

    rr = org.get("review_request")
    if not isinstance(rr, dict):
        problems.append(f"{where}: review_request must be a mapping with room and template")
    else:
        _unknown(f"{where}: review_request", rr, REVIEW_KEYS, problems)
        for k in ("room", "template"):
            if not isinstance(rr.get(k), str) or not rr.get(k).strip():
                problems.append(f"{where}: review_request.{k} is required (a string)")
        if isinstance(rr.get("template"), str):
            problems.extend(_template_problems(f"{where}: review_request.template", rr["template"], TEMPLATE_FIELDS))
    return problems


def _cell(s: object) -> str:
    return str(s).replace("|", "\\|").replace("\n", " ").strip()


def _code(s: object) -> str:
    return f"`{_cell(s)}`"


def _when(when: object) -> str:
    if when == "always":
        return "always"
    parts = []
    for k, v in (when or {}).items():
        names = ", ".join(_code(x) for x in v)
        parts.append(f"a changed path matches {names}" if k == "paths" else f"the PR or work ticket has label {names}")
    return " or ".join(parts)


def org_markdown(org: dict, org_path: str) -> dict[str, str]:
    """The generated {{org_*}} placeholders for a valid org."""
    types = {t["id"]: t for t in org["ticket_types"]}
    rows = ["| Ticket type | Project | Issue type | Role | Summary |", "| --- | --- | --- | --- | --- |"]
    for t in org["ticket_types"]:
        rows.append(f"| {_code(t['id'])} | {_code(t['project'])} | {_cell(t['issue_type'])} | {t['role']} | "
                    f"{_code(t['summary']) if t.get('summary') else '-'} |")
    gates = ["| Gate | Ticket | Applies when | Links | Filed by | PR line | Approved when |",
             "| --- | --- | --- | --- | --- | --- | --- |"]
    for g in org["gates"]:
        t = types[g["ticket"]]
        statuses = ", ".join(_cell(s) for s in g.get("approved_statuses") or []) or "the approver says so"
        gates.append(f"| {_code(g['id'])} | {_code(g['ticket'])} in {_code(t['project'])} | {_when(g['when'])} | "
                     f"{', '.join(g.get('links') or []) or '-'} | {g['filed_by']} | `{_cell(g['pr_line'])}: <KEY>` | "
                     f"{statuses} |")
    rr = org["review_request"]
    review = (f"Room: {rr['room'].strip()}. Template:\n\n````text\n{rr['template'].rstrip()}\n````")
    if org.get("placeholder"):
        status = (f"**The org overlay is not applied.** This harness carries the public placeholder "
                  f"(`{org_path}`, `placeholder: true`): its projects and room are not real. File no ticket and add "
                  f"no gate line. Say in the PR and on the work ticket that the company's org overlay is not "
                  f"applied, and list the gates below that would apply. Still draft the review request.")
    else:
        status = (f"The gates below are the `{org['name']}` org overlay's (`{org_path}/org.yaml`). Run them as "
                  f"written.")
    return {"org_status": status, "org_ticket_types": "\n".join(rows), "org_gates": "\n".join(gates),
            "org_review_request": review}


def _org(root: Path, h: str, entry: dict, profile: dict[str, str], problems: list[str],
         warnings: list[str]) -> tuple[Path | None, dict[str, str]]:
    """(the org directory, the params it adds) for the harness's `org:`, or (None, {}) when it names none."""
    rel = entry.get("org")
    if not rel:
        return None, {}
    if h in NO_ORG:
        problems.append(f"{h}: takes no org overlay (the work/home wall); remove org: {rel} from targets.yaml")
        return None, {}
    d = (root / rel).resolve()
    if not d.is_relative_to((root / "orgs").resolve()) or not (d / "org.yaml").is_file():
        problems.append(f"{h}: org {rel} must be a directory under orgs/ with an org.yaml")
        return None, {}
    try:
        org = yaml.safe_load((d / "org.yaml").read_text())
    except (OSError, yaml.YAMLError) as e:
        problems.append(f"{h}: cannot read {rel}/org.yaml: {e}")
        return None, {}
    errs = validate_org(org, f"{rel}/org.yaml", set(profile))
    if not errs and org["name"] != d.name:
        errs.append(f"{rel}/org.yaml: name {org['name']!r} must be the directory's name {d.name!r}")
    if not (d / "skills" / "org-process" / "SKILL.md").is_file():
        errs.append(f"{rel}: skills/org-process/SKILL.md is missing (the company's own flow skill goes there)")
    problems.extend(errs)
    if errs:
        return None, {}
    if org.get("placeholder"):
        warnings.append(f"{h}: {rel} is a placeholder org (placeholder: true): agents file no approval tickets")
    return d, {**(org.get("params") or {}), **org_markdown(org, rel.rstrip("/"))}


_NAME = re.compile(r"^name:\s*['\"]?([^'\"\n]+?)['\"]?\s*$", re.MULTILINE)


def _skill_name(skill_md: Path) -> str | None:
    """The frontmatter `name:` of a SKILL.md, if it has one."""
    text = skill_md.read_text(errors="replace")
    if not text.startswith("---"):
        return None
    end = text.find("\n---", 3)
    m = _NAME.search(text[3:end if end > 0 else len(text)])
    return m.group(1).strip() if m else None


def plan(root: Path = ROOT, warnings: list[str] | None = None
         ) -> tuple[list[tuple[Path, Path, dict[str, bytes] | None]], list[str]]:
    """(source, destination, rendered files) for every copy that is out of sync, and problems. A left-over skill
    directory is (it, it, None): `write` deletes it. Notes that are not errors (a placeholder org) are appended to
    `warnings`."""
    warnings = [] if warnings is None else warnings
    shared = root / "shared" / "work-system"
    t = yaml.safe_load((shared / "targets.yaml").read_text())
    stale: list[tuple[Path, Path, dict[str, bytes] | None]] = []
    problems: list[str] = []
    hook_src = shared / t["hook"]
    harnesses = t["harnesses"]
    if isinstance(harnesses, list):  # the older form: a plain list, no profiles
        harnesses = {h: {} for h in harnesses}
    for h, entry in harnesses.items():
        entry = entry or {}
        hd = root / "harnesses" / h
        if not hd.is_dir():
            problems.append(f"{h}: harnesses/{h} does not exist")
            continue
        params = _profile(shared, h, entry, problems)
        org_dir, org_params = _org(root, h, entry, params, problems, warnings)
        params = {**params, **org_params}  # the org wins
        sources = [(shared / "skills" / s, s, True) for s in list(t["skills"]) + list(entry.get("skills") or [])]
        own = set(entry.get("own_skills") or [])
        for s in sorted(own & {n for _, n, _ in sources}):
            problems.append(f"{h}: own_skills names {s}, which the shared layer renders")
        if org_dir is not None:
            for d in sorted(p for p in (org_dir / "skills").iterdir() if p.is_dir()):
                if d.name in {n for _, n, _ in sources} | own:
                    problems.append(f"{h}: org skill {d.name} has the name of a shared or harness skill")
                    continue
                if (d / "SKILL.md").is_file() and _skill_name(d / "SKILL.md") != d.name:
                    problems.append(f"{h}: {d.relative_to(root)}/SKILL.md must have frontmatter name: {d.name}")
                sources.append((d, d.name, False))  # the company's own files: copied verbatim, never rendered
        for src, s, rendered in sources:
            dst = hd / "skills" / s
            if not src.is_dir():
                problems.append(f"{h}: shared skill {s} does not exist")
                continue
            where = f"{h}: {src.relative_to(root)}"
            want = {rel: render(b, params, f"{where}/{rel}", problems) if rendered else b
                    for rel, b in _files(src).items()}
            if not dst.is_dir() or want != _files(dst):
                stale.append((src, dst, want))
        produced = {s for _, s, _ in sources} | own
        skills_dir = hd / "skills"
        org_failed = bool(entry.get("org")) and org_dir is None and h not in NO_ORG
        for d in sorted(p for p in skills_dir.iterdir() if p.is_dir()) if skills_dir.is_dir() and not org_failed else []:
            if d.name not in produced:
                stale.append((d, d, None))  # left over: an org skill removed or renamed, or a dropped shared skill
        dst = hd / "native" / "claude-code" / "hooks" / hook_src.name
        want_hook = render(hook_src.read_bytes(), params, f"{h}: {t['hook']}", problems)
        if not dst.is_file() or dst.read_bytes() != want_hook:
            stale.append((hook_src, dst, {"": want_hook}))
        settings = hd / "native" / "claude-code" / "settings.json"
        try:
            pre = json.loads(settings.read_text()).get("hooks", {}).get("PreToolUse", [])
        except (OSError, ValueError) as e:
            problems.append(f"{h}: cannot read {settings.relative_to(root)}: {e}")
            continue
        entries = [e for e in pre if any(x.get("command") == t["hook_command"] for x in e.get("hooks", []))]
        matchers = " ".join(e.get("matcher", "") for e in entries)
        if not entries:
            problems.append(f"{h}: settings.json does not register {t['hook_command']!r} on PreToolUse")
        elif "Bash" not in matchers or "mcp__" not in matchers:
            problems.append(f"{h}: the work-system hook must match Bash and mcp__ tools (matcher: {matchers!r})")
    return stale, problems


def write(stale: list[tuple[Path, Path, dict[str, bytes] | None]], root: Path = ROOT) -> None:
    for src, dst, files in stale:
        if files is None:
            shutil.rmtree(dst)
            print(f"removed {dst.relative_to(root)} (no longer produced)")
            continue
        if src.is_dir():
            if dst.exists():
                shutil.rmtree(dst)
            for rel, data in files.items():
                (dst / rel).parent.mkdir(parents=True, exist_ok=True)
                (dst / rel).write_bytes(data)
        else:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(files[""])
            shutil.copymode(src, dst)
        print(f"synced {dst.relative_to(root)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--check", action="store_true", help="exit 1 when a copy differs; write nothing")
    args = ap.parse_args(argv)
    warnings: list[str] = []
    stale, problems = plan(warnings=warnings)
    for w in warnings:
        print(f"warning: {w}", file=sys.stderr)
    if args.check:
        for src, dst, files in stale:
            if files is None:
                print(f"error: {dst.relative_to(ROOT)} is not produced by the shared layer, the org or own_skills "
                      "(a removed or renamed skill?); python scripts/sync_shared.py deletes it", file=sys.stderr)
                continue
            print(f"error: {dst.relative_to(ROOT)} differs from the rendering of {src.relative_to(ROOT)} "
                  "(edit shared/work-system/, then python scripts/sync_shared.py)", file=sys.stderr)
    elif not problems:
        write(stale)
    for p in problems:
        print(f"error: {p}", file=sys.stderr)
    if (args.check and stale) or problems:
        return 1
    print("shared work-system layer in sync")
    return 0


if __name__ == "__main__":
    sys.exit(main())
