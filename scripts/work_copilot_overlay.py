"""Work Copilot's config from the company org overlay (KAN-381).

The org overlay (`orgs/<org>/org.yaml`, the harness's `org:` in shared/work-system/targets.yaml) already sets the work
site, the Jira project and the review room for the work-system skills. Work Copilot needs the same values. This script
renders them as Work Copilot's overlay file, so one file feeds both instead of two hand-edited ones:

    python3 scripts/work_copilot_overlay.py --harness work-default --out /abs/work-copilot-overlay.json
    <your Work Copilot launcher> --data-dir <your data dir> overlay apply /abs/work-copilot-overlay.json

(`py -3` on Windows. The launcher is Work Copilot's ./run.sh or .\\run.ps1, which changes to its own directory, so
the file's path must be absolute; --out prints both commands with it.)

The values are the harness's effective ones, as scripts/sync_shared.py renders them: the profile's params with the
org's on top, so an org that leaves out kb_site or kb_space gets the profile's. `--at <commit>` reads targets.yaml,
the profile and the org at that commit (install_local.py passes the pinned revision it installs).

The file holds only what org.yaml and the profile hold: no credentials. A placeholder org (placeholder: true, the
public example) renders with `placeholder: true`, and Work Copilot reports it as not applied.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Iterator

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_shared  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "work-copilot.overlay/v1"
PLACEHOLDER_NOTE = "(placeholder org: values are examples)"
WINDOWS = os.name == "nt"  # tests set it to check the Windows commands on any OS

# Work Copilot's formats: these must stay identical to work_copilot/overlay.py's _TEXT and _FIELDS, which refuse
# anything else. Both repositories test the same cases, and Work Copilot's tests hold this script's output as a golden.
_TEXT = re.compile(r"[^\x00-\x1f\x7f-\x9f  ]{1,200}")
FORMATS = {
    "name": _TEXT,
    "source": _TEXT,
    "work_site": re.compile(r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,62})(?:\.[A-Za-z0-9-]{1,63}){1,10}"),
    "kb_space": re.compile(r"~?[A-Za-z0-9][A-Za-z0-9_-]{0,63}"),
    "jira_project": re.compile(r"[A-Z][A-Z0-9_]{0,19}"),
    "room": _TEXT,
}
EXPECTED = {
    "name": "1 to 200 characters, no control characters or line breaks",
    "work_site": "a host name such as company.atlassian.net (no path; a scheme and trailing slash are dropped)",
    "kb_space": "a space key such as ENG, or ~user for a personal space (letters, digits, _ or -, up to 64)",
    "jira_project": "a Jira project key such as ENG (capital letters, digits or _, starting with a letter, up to 20)",
    "room": "1 to 200 characters, no control characters or line breaks",
}
_SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")


def _posix(rel: str) -> str:
    """A path from the repository root as written in targets.yaml or on a command line: `/` separators, no trailing
    `/` or `\\`."""
    return rel.replace("\\", "/").rstrip("/")


def _build(org: dict, where: str, params: dict, origin: dict[str, str]) -> dict:
    """The overlay from a validated org and the effective params; ValueError naming each value Work Copilot would
    refuse, with the file it came from, the field and the form expected."""
    work = next((t for t in org["ticket_types"] if t.get("role") == "work"), None)
    raw = {  # overlay field -> (value, the file it came from, the field there)
        "name": (org["name"], where, "name"),
        "work_site": (params.get("kb_site"), origin.get("kb_site", where), "params.kb_site"),
        "kb_space": (params.get("kb_space"), origin.get("kb_space", where), "params.kb_space"),
        "jira_project": (work["project"] if work else None, where,
                         f"ticket_types[{org['ticket_types'].index(work)}].project" if work else ""),
        "room": ((org.get("review_request") or {}).get("room"), where, "review_request.room"),
    }
    out = {"schema": SCHEMA, "name": None, "placeholder": bool(org.get("placeholder", False)), "source": where}
    problems = []
    for key, (value, path, field) in raw.items():
        if value is None:
            continue
        value = str(value).strip()
        if key == "work_site":
            value = _SCHEME.sub("", value).rstrip("/")
        if not value and key != "name":
            continue  # an empty value is left out, as a missing one is
        if not FORMATS[key].fullmatch(value):
            problems.append(f"{path}: {field} {value!r} is not valid for Work Copilot; expected {EXPECTED[key]}")
            continue
        out[key] = value
    if problems:
        raise ValueError("\n".join(problems))
    return out


def overlay(org: dict, where: str, profile: dict | None = None, profile_where: str = "the harness profile") -> dict:
    """Work Copilot's overlay for a valid org.yaml, its params over `profile`'s as sync_shared merges them;
    ValueError naming every problem otherwise."""
    problems = sync_shared.validate_org(org, where, set(profile) if profile is not None else None)
    if problems:
        raise ValueError("\n".join(problems))
    own = org.get("params") or {}
    origin = {k: where if k in own else profile_where for k in ("kb_site", "kb_space")}
    return _build(org, where, {**(profile or {}), **own}, origin)


def _targets(root: Path) -> dict:
    t = yaml.safe_load((root / "shared/work-system/targets.yaml").read_text(encoding="utf-8")) or {}
    harnesses = t.get("harnesses") if isinstance(t, dict) else None
    if isinstance(harnesses, list):  # the older form sync_shared accepts: a plain list, no profiles
        harnesses = {h: {} for h in harnesses}
    if not isinstance(harnesses, dict):
        raise ValueError("shared/work-system/targets.yaml: harnesses must be a mapping")
    return {h: (e if isinstance(e, dict) else {}) for h, e in harnesses.items()}


def org_for(root: Path, harness: str) -> str | None:
    """The harness's `org:` from targets.yaml (a path from the repository root), or None."""
    entry = _targets(root).get(harness) or {}
    org = entry.get("org")
    return _posix(org) or None if isinstance(org, str) else None


def render(root: Path, *, harness: str | None = None, org: str | None = None) -> dict:
    """The overlay for `harness`'s org (or `org` in its place), with the harness profile's params beneath the org's.
    `org` alone takes the profile of the harness that names it in targets.yaml."""
    targets = _targets(root)
    rel = _posix(org) if org else None
    if rel is not None:
        d = (root / rel).resolve()
        if not d.is_relative_to((root / "orgs").resolve()) or not (d / "org.yaml").is_file():
            raise ValueError(f"{rel} must be a directory under orgs/ with an org.yaml")
        rel = d.relative_to(root.resolve()).as_posix()
        if harness is None:
            harness = next((h for h, e in targets.items() if isinstance(e.get("org"), str)
                            and _posix(e["org"]) == rel), None)
            if harness is None:
                raise ValueError(f"no harness in shared/work-system/targets.yaml names {rel}; pass --harness to say "
                                 f"whose profile fills it")
    if harness not in targets:
        raise ValueError(f"{harness} is not a harness in shared/work-system/targets.yaml")
    entry = dict(targets[harness])
    if rel is None:
        rel = org_for(root, harness)
        if not rel:
            raise ValueError(f"{harness} names no org overlay in shared/work-system/targets.yaml")
    entry["org"] = rel
    # sync_shared's own helpers (private, but they are the one definition of the profile, the org's validation and
    # the merge that the harness's skills are rendered with; a copy here could drift from them)
    problems: list[str] = []
    profile = sync_shared._profile(root / "shared/work-system", harness, entry, problems)
    org_dir, org_params = sync_shared._org(root, harness, entry, profile, problems, [])
    if problems or org_dir is None:
        raise ValueError("\n".join(problems) or f"{harness}: org {rel} did not load")
    params = {**profile, **org_params}  # the org wins, as in sync_shared.plan
    where = f"{rel}/org.yaml"
    data = yaml.safe_load((org_dir / "org.yaml").read_text(encoding="utf-8"))
    own = data.get("params") or {}
    profile_where = f"shared/work-system/{_posix(str(entry.get('profile')))}"
    origin = {k: where if k in own else profile_where for k in ("kb_site", "kb_space")}
    return _build(data, where, params, origin)


def _git(root: Path, *args: str) -> bytes:
    r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, check=False)
    if r.returncode != 0:
        raise ValueError(f"git {' '.join(args[:2])} failed: {r.stderr.decode('utf-8', 'replace').strip()}")
    return r.stdout


@contextlib.contextmanager
def tree(root: Path, at: str | None = None) -> Iterator[Path]:
    """`root` itself, or (with `at`) targets.yaml, the profiles and orgs/ as they were at that commit, in a temporary
    directory laid out as in the repository."""
    if not at:
        yield root
        return
    if at.startswith("-"):
        raise ValueError(f"--at {at!r} is not a commit")
    try:
        commit = _git(root, "rev-parse", "--verify", "--quiet", f"{at}^{{commit}}").decode().strip()
    except ValueError:
        raise ValueError(f"--at {at}: no such commit in {root}") from None
    with tempfile.TemporaryDirectory(prefix="work-copilot-overlay-") as tmp:
        names = _git(root, "ls-tree", "-r", "-z", "--name-only", commit, "--",
                     "shared/work-system/targets.yaml", "shared/work-system/profiles", "orgs")
        for name in filter(None, names.decode("utf-8").split("\0")):
            dst = Path(tmp, *name.split("/"))
            if not dst.resolve().is_relative_to(Path(tmp).resolve()):
                raise ValueError(f"{commit}: {name} is outside the tree")
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(_git(root, "show", f"{commit}:{name}"))
        yield Path(tmp)


def _windows(windows: bool | None) -> bool:
    return WINDOWS if windows is None else windows


def quote(word: str, windows: bool | None = None) -> str:
    """One word for the shell a person pastes into: PowerShell single quotes on Windows (double quotes would expand
    `$`), as install_local quotes its other lines, else POSIX quoting."""
    return "'" + word.replace("'", "''") + "'" if _windows(windows) else shlex.quote(word)


def python(windows: bool | None = None) -> str:
    return "py -3" if _windows(windows) else "python3"


def default_out(home: Path | None = None, env: dict[str, str] | None = None, windows: bool | None = None) -> Path:
    """Where install_local has the overlay written unless told otherwise: the user's own config folder
    (%APPDATA%\\team-harness on Windows, else $XDG_CONFIG_HOME or ~/.config, then team-harness), never the current
    folder, which may be a company repository."""
    home = home or Path.home()
    env = os.environ if env is None else env
    if _windows(windows):
        base = Path(env["APPDATA"]) if env.get("APPDATA") else home / "AppData" / "Roaming"
    else:
        base = Path(env["XDG_CONFIG_HOME"]) if env.get("XDG_CONFIG_HOME") else home / ".config"
    return base / "team-harness" / "work-copilot-overlay.json"


def write(out: Path, text: str) -> Path:
    """Write the overlay to `out`, creating its folder (private on POSIX) when missing; returns the absolute path."""
    out = out.expanduser().resolve()  # absolute: Work Copilot's launcher changes to its own directory first
    if not out.parent.exists():
        out.parent.mkdir(parents=True, mode=0o700)
    out.write_text(text, encoding="utf-8")
    return out


def apply_commands(out: Path, windows: bool | None = None) -> tuple[str, str]:
    """(the command to apply `out`, an example of it with Work Copilot's own launcher, which passes its arguments
    on to `python -m work_copilot`)."""
    f = quote(str(out), windows)
    launcher = r".\run.ps1" if _windows(windows) else "./run.sh"
    return (f"<your Work Copilot launcher> --data-dir <your data dir> overlay apply {f}",
            f"for example, from your Work Copilot checkout: {launcher} --data-dir <your data dir> overlay apply {f}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--harness", help="the harness whose org overlay to render (its org: in targets.yaml)")
    ap.add_argument("--org", help="an org directory, such as orgs/example-co (in place of the harness's org:)")
    ap.add_argument("--at", metavar="COMMIT", help="read targets.yaml, the profile and the org at this commit")
    ap.add_argument("--out", type=Path, help="write the overlay here (default: print it and write nothing); "
                                             "install_local suggests a file in your own config folder")
    a = ap.parse_args(argv)
    if not (a.harness or a.org):
        ap.error("give --harness or --org")
    try:
        with tree(ROOT, a.at) as root:
            data = render(root, harness=a.harness, org=a.org)
    except (OSError, ValueError, yaml.YAMLError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except (AttributeError, TypeError, KeyError) as e:  # a malformed targets.yaml or profile
        print(f"error: shared/work-system/targets.yaml or the profile is malformed: {e!r}", file=sys.stderr)
        return 2
    note = f" {PLACEHOLDER_NOTE}" if data["placeholder"] else ""
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if a.out:
        out = write(a.out, text)
        apply, example = apply_commands(out)
        print(f"wrote {out}{note}; now apply it:\n  {apply}\n  {example}")
    else:
        sys.stdout.write(text)
        if note:
            print(note.strip(), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
