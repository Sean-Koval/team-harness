#!/usr/bin/env python3
"""Bring a team work skill into the shared layer, checked, in one command (KAN-511).

    python scripts/add_skill.py ~/work-skills/deploy-notes --harness work-default --key KAN-123
    python scripts/add_skill.py --check        # CI (tests/test_add_skill.py): every shared skill passes the rules

The skill is a directory with a SKILL.md. It is copied to `shared/work-system/skills/<name>/` with LF line ends and no
byte-order mark, its frontmatter gets `harnesses: [<harness>]` (the registration: sync_shared.py ships it to those
harnesses only) and `changes/<KEY>.added.md` gets a bullet. Nothing is copied when any rule fails:

- frontmatter `name:` (kebab-case, free in the shared layer, every org and every harness's own skills) and
  `description:`;
- no Atlassian MCP tool name: skills call ai-dlc's roles, never a vendor's tools (spec section 2;
  tests/test_skill_tool_names.py holds the pattern equal);
- no secret, no e-mail address, no hostname other than example.*, localhost or github.com: write a `{{placeholder}}`;
- no person or site a profile fills in (`owner`, `kb_site`, `kb_space`): write its `{{placeholder}}`;
- no word from a local deny list (`--deny WORD`, or a file of words named by TEAM_HARNESS_DENY): keep your company's
  and customers' names there, on your machine, never in this repository;
- every `{{placeholder}}` is one the harness's profile or org fills.

Then commit the sources only (the skill and the fragment) and open a PR. After merge, generated.yml renders the skill
into the harness and moves `candidate`; `stable` moves only by scripts/promote.py, with a flightdeck verdict and a
second approver.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import sync_shared  # noqa: E402

SKILLS = Path("shared/work-system/skills")
NAME_RULE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
IGNORED = {".DS_Store", "Thumbs.db", "desktop.ini"}
MAX_BYTES = 256 * 1024
IDENTITY_PARAMS = ("owner", "kb_site", "kb_space")  # profile values that name a person or a site

# The same pattern as tests/test_skill_tool_names.py (a test holds them equal).
ATLASSIAN_TOOL = re.compile(
    r"(?<![A-Za-z0-9])(?:[A-Za-z]+(?:Jira|Confluence|Atlassian)[A-Za-z]*"
    r"|(?:jira|confluence)_[a-z_]+"
    r"|atlassian[A-Z][A-Za-z]*"
    r"|execute_?(?:Read|Write|Destructive|read|write|destructive)"
    r"|getTeamworkGraph[A-Za-z]*"
    r"|mcp__(?i:\w*(?:atlassian|jira|confluence)\w*?)__\w+"
    r"|mcp__[\w-]+?__(?i:\w*(?:jira|confluence|atlassian)\w*))(?![A-Za-z0-9])")

SECRETS = [
    ("private key", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("GitHub token", re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})")),
    ("AWS access key", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    ("Slack token", re.compile(r"\bxox[abposr]-[A-Za-z0-9-]{10,}")),
    ("Atlassian API token", re.compile(r"\bATATT[A-Za-z0-9_\-=]{20,}")),
    ("API key", re.compile(r"\bsk-(?:ant-)?[A-Za-z0-9_\-]{20,}")),
    ("Google API key", re.compile(r"\bAIza[0-9A-Za-z_\-]{30,}")),
    ("JWT", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.")),
    ("credential value", re.compile(
        r"(?i)\b(?:password|passwd|secret|api[_-]?key|token|bearer)\b[\"']?\s*[:=]\s*[\"']?"
        r"(?!\$\{|\$[A-Z_]|<|\{\{|\*+|x+\b)[A-Za-z0-9+/_\-.]{12,}")),
]
EMAIL = re.compile(r"[\w.+-]+@((?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,})")
HOST = re.compile(r"(?<![\w@.{-])((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+"
                  r"(?:com|net|org|io|dev|ai|co|app|cloud|biz|info|us|uk|de|fr|in|internal|corp|local))(?![\w-])",
                  re.IGNORECASE)
ALLOWED_HOSTS = re.compile(r"(?i)^(?:(?:[\w-]+\.)*example\.(?:com|org|net)|localhost|github\.com)$")


def _frontmatter(text: str) -> tuple[dict | None, str]:
    """(frontmatter, error): the top-level `key: value` lines between the first two `---` lines. Read line by line,
    as Claude Code does, not as strict YAML: a description may hold an unquoted colon."""
    if not text.startswith("---\n"):
        return None, "SKILL.md must start with a --- frontmatter block"
    end = text.find("\n---", 3)
    if end < 0:
        return None, "SKILL.md frontmatter has no closing ---"
    data: dict = {}
    key = None
    for line in text[4:end].split("\n"):
        m = re.match(r"^([A-Za-z_][\w-]*):\s*(.*)$", line)
        if m:
            key = m.group(1)
            value = m.group(2).strip()
            data[key] = "" if value in (">", ">-", "|", "|-") else value.strip("'\"")
        elif key and line.startswith((" ", "\t")):  # a folded or literal block value
            data[key] = (data[key] + " " + line.strip()).strip()
    if "harnesses" in data:
        inner = data["harnesses"].strip("[]")
        data["harnesses"] = [n.strip().strip("'\"") for n in inner.split(",") if n.strip()]
    return data, ""


def _identity_values(root: Path) -> set[str]:
    out = set()
    for p in sorted((root / "shared/work-system/profiles").glob("*.yaml")):
        params = (yaml.safe_load(p.read_text(encoding="utf-8")) or {}).get("params") or {}
        out |= {str(params[k]).strip() for k in IDENTITY_PARAMS if k in params}
    return {v for v in out if len(v) >= 3 and not re.search(r"\s", v)}


def deny_words(extra: list[str] | None = None) -> list[str]:
    words = list(extra or [])
    path = os.environ.get("TEAM_HARNESS_DENY")
    if path:
        words += [w.strip() for w in Path(path).read_text(encoding="utf-8").splitlines()
                  if w.strip() and not w.lstrip().startswith("#")]
    return words


def read_files(src: Path) -> tuple[dict[str, str], list[str]]:
    """The skill's text files (relative POSIX path -> text, LF, no BOM), and problems."""
    files, problems = {}, []
    for p in sorted(src.rglob("*")):
        rel = p.relative_to(src).as_posix()
        if p.name in IGNORED or "__pycache__" in p.parts:
            continue
        if p.is_symlink():
            problems.append(f"{rel}: a symlink; copy the file itself")
        elif p.is_file():
            data = p.read_bytes()
            if len(data) > MAX_BYTES:
                problems.append(f"{rel}: larger than {MAX_BYTES // 1024} KiB")
                continue
            try:
                text = data.decode("utf-8-sig")
            except UnicodeDecodeError:
                problems.append(f"{rel}: not UTF-8 text; a skill holds text only")
                continue
            files[rel] = text.replace("\r\n", "\n").replace("\r", "\n")
    return files, problems


def content_problems(files: dict[str, str], identity: set[str], deny: list[str]) -> list[str]:
    """The wall and seam rules over every line of every file."""
    out = []
    deny_res = [(w, re.compile(rf"(?i)(?<![\w]){re.escape(w)}(?![\w])")) for w in deny]
    ident_res = [(v, re.compile(rf"(?<![\w.]){re.escape(v)}(?![\w])")) for v in sorted(identity)]
    for rel, text in files.items():
        for n, line in enumerate(text.splitlines(), 1):
            at = f"{rel}:{n}"
            out += [f"{at}: names the vendor tool {m.group(0)}; call ai-dlc's role (tracker_*, knowledge_*) instead"
                    for m in ATLASSIAN_TOOL.finditer(line)]
            out += [f"{at}: looks like a {what}; name the credential, never its value" for what, rx in SECRETS
                    if rx.search(line)]
            emails = list(EMAIL.finditer(line))
            out += [f"{at}: an e-mail address ({m.group(0)}); use a {{{{placeholder}}}} or a role" for m in emails
                    if not ALLOWED_HOSTS.match(m.group(1))]
            email_hosts = {m.group(1).lower() for m in emails}
            out += [f"{at}: the host {m.group(1)}; use example.com or a {{{{placeholder}}}}" for m in HOST.finditer(line)
                    if not ALLOWED_HOSTS.match(m.group(1)) and m.group(1).lower() not in email_hosts]
            out += [f"{at}: {v!r} is a profile's person or site; write its {{{{placeholder}}}}" for v, rx in ident_res
                    if rx.search(line)]
            out += [f"{at}: {w!r} is on your deny list" for w, rx in deny_res if rx.search(line)]
    return out


def frontmatter_problems(name: str, files: dict[str, str]) -> tuple[dict, list[str]]:
    if "SKILL.md" not in files:
        return {}, ["no SKILL.md at the top of the skill directory"]
    fm, err = _frontmatter(files["SKILL.md"])
    if fm is None:
        return {}, [err]
    out = []
    if fm.get("name") != name:
        out.append(f"SKILL.md frontmatter name must be {name!r} (the directory's name), not {fm.get('name')!r}")
    if not NAME_RULE.match(name):
        out.append(f"skill name {name!r} must be kebab-case (a-z, 0-9, -)")
    desc = fm.get("description")
    if not isinstance(desc, str) or len(desc.strip()) < 20:
        out.append("SKILL.md frontmatter needs a description: when to use the skill and what it does")
    return fm, out


def taken_names(root: Path, targets: dict) -> set[str]:
    taken = {d.name for d in (root / SKILLS).iterdir() if d.is_dir()}
    for org in (root / "orgs").glob("*/skills/*"):
        taken.add(org.name)
    for entry in (targets.get("harnesses") or {}).values():
        taken |= set((entry or {}).get("own_skills") or [])
    return taken


def harness_params(root: Path, targets: dict, h: str, problems: list[str]) -> set[str]:
    entry = (targets.get("harnesses") or {}).get(h)
    if entry is None:
        problems.append(f"--harness {h}: shared/work-system/targets.yaml does not list it")
        return set()
    shared = root / "shared" / "work-system"
    params = sync_shared._profile(shared, h, entry, problems)
    _, org_params = sync_shared._org(root, h, entry, params, problems, [])
    return set(params) | set(org_params)


def with_harnesses(skill_md: str, harnesses: list[str]) -> str:
    """SKILL.md with `harnesses: [..]` right after its name line (sync_shared.py reads that one-line form)."""
    line = f"harnesses: [{', '.join(harnesses)}]"
    end = skill_md.find("\n---", 4)
    head = [ln for ln in skill_md[4:end].split("\n") if not ln.startswith("harnesses:")]
    i = next(i for i, ln in enumerate(head) if ln.startswith("name:"))
    head.insert(i + 1, line)
    return "---\n" + "\n".join(head) + skill_md[end:]


def add(src: Path, harnesses: list[str], key: str, deny: list[str], root: Path = ROOT) -> list[str]:
    """Check and copy one skill. Returns problems; nothing is written unless there are none."""
    src = src.expanduser().resolve()
    if not src.is_dir():
        return [f"{src}: not a directory (give the skill's directory, the one holding SKILL.md)"]
    if not re.fullmatch(r"[A-Z][A-Z0-9]*-\d+", key):
        return [f"--key {key!r}: give the ticket key, such as KAN-123"]
    name = src.name
    targets = yaml.safe_load((root / "shared/work-system/targets.yaml").read_text(encoding="utf-8"))
    files, problems = read_files(src)
    fm, fp = frontmatter_problems(name, files)
    problems += fp
    if name in taken_names(root, targets):
        problems.append(f"skill name {name!r} is taken (shared, org or a harness's own skill); rename the directory")
    if "harnesses" in fm and sorted(fm.get("harnesses") or []) != sorted(harnesses):
        problems.append(f"SKILL.md says harnesses: {fm['harnesses']}; drop the line, --harness sets it")
    problems += content_problems(files, _identity_values(root), deny)
    for h in harnesses:
        allowed = harness_params(root, targets, h, problems)
        for rel, text in files.items():
            for p in sorted({m.group(1) for m in sync_shared.PLACEHOLDER.finditer(text)} - allowed):
                if allowed:
                    problems.append(f"{rel}: {{{{{p}}}}} is not a parameter {h}'s profile fills")
    if problems:
        return problems
    dst = root / SKILLS / name
    dst.mkdir(parents=True)
    for rel, text in files.items():
        if rel == "SKILL.md":
            text = with_harnesses(text, harnesses)
        (dst / rel).parent.mkdir(parents=True, exist_ok=True)
        (dst / rel).write_bytes(text.encode("utf-8"))
    first = " ".join(str(fm["description"]).split())
    first = first.split(". ")[0].rstrip(".")
    frag = root / "changes" / f"{key}.added.md"
    old = frag.read_text(encoding="utf-8") if frag.is_file() else ""
    frag.write_text(old + f"- {', '.join(harnesses)}: + `{name}` skill. {first}.\n", encoding="utf-8")
    return []


def check(root: Path = ROOT, deny: list[str] | None = None) -> list[str]:
    """The intake rules over every shared skill (placeholders are sync_shared.py --check's)."""
    out = []
    identity = _identity_values(root)
    for d in sorted(p for p in (root / SKILLS).iterdir() if p.is_dir() and not p.name.startswith((".", "_"))):
        files, problems = read_files(d)
        problems += frontmatter_problems(d.name, files)[1]
        problems += content_problems(files, identity, deny or [])
        out += [f"{SKILLS.as_posix()}/{d.name}/{p}" for p in problems]
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("skill", nargs="?", type=Path, help="the skill's directory (holds SKILL.md)")
    ap.add_argument("--harness", action="append", help="a harness it ships to (repeat for more), e.g. work-default")
    ap.add_argument("--key", help="the ticket key, e.g. KAN-123: names the changelog fragment")
    ap.add_argument("--deny", action="append", default=[], help="a word that must not appear (repeat); see also "
                    "the TEAM_HARNESS_DENY file")
    ap.add_argument("--check", action="store_true", help="check every shared skill instead of adding one")
    a = ap.parse_args(argv)
    deny = deny_words(a.deny)
    if a.check:
        problems = check(ROOT, deny)
        for p in problems:
            print(f"error: {p}")
        print("ok: every shared skill passes intake" if not problems else f"{len(problems)} problem(s)")
        return 1 if problems else 0
    if a.skill is None or not a.harness or not a.key:
        ap.error("give the skill's directory, --harness and --key (or --check)")
    problems = add(a.skill, a.harness, a.key, deny, root=ROOT)
    for p in problems:
        print(f"error: {p}")
    if problems:
        print("nothing copied")
        return 1
    name = a.skill.expanduser().resolve().name
    print(f"added {SKILLS.as_posix()}/{name}/ for {', '.join(a.harness)} and changes/{a.key}.added.md")
    print(f"next: commit those two on a {a.key}-... branch (sources only) and open the PR; after merge it ships "
          "in the next candidate revision, and stable moves only by scripts/promote.py")
    return 0


if __name__ == "__main__":
    sys.exit(main())
