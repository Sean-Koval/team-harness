"""Rule 8 of the work-system PR check: the PR's shape, so parallel PRs stay small and don't conflict (KAN-516).

- **Diff budget.** Changed lines (additions plus deletions) and changed files, not counting tests, changelog fragments
  or generated files, stay within the budget, unless the body has a `Budget: <reason>` line.
- **Generated files.** A PR doesn't edit a file the build writes (the shared layer's copies, locks, `CHANGELOG.md`),
  unless it is the post-merge regeneration PR (branch `bot/generated` in the same repository) or carries the
  `generated-files` label. A release fold that deletes fragments may edit `CHANGELOG.md`.
- **Changelog fragment.** A PR that changes source adds `<changes dir>/<KEY>.md` or `<changes dir>/<KEY>.<kind>.md`.

The settings come from a fenced block in the repository's `AGENTS.md`, read at the PR's base commit (so a PR can't
loosen its own budget), with defaults for a repository that has none:

    ```work-system-pr
    diff-budget: 500 lines, 25 files
    generated: harnesses/**, CHANGELOG.md, **/harness.lock
    tests: tests/**, **/test_*.py
    changes: changes
    ```

`generated` and `tests` are comma-separated globs (`**/` also matches no directory); a later `!glob` takes paths back
out, as in .gitignore. `none` turns a setting off. Standard library only.
"""

from __future__ import annotations

import fnmatch
import re
import urllib.error
from collections.abc import Callable
from dataclasses import dataclass, field

CONFIG_FILE = "AGENTS.md"
REGEN_BRANCH = "bot/generated"
REGEN_LABEL = "generated-files"
DEFAULT_LINES = 500
DEFAULT_FILES = 25
DEFAULT_GENERATED = ("harnesses/**", "CHANGELOG.md", "**/harness.lock")
DEFAULT_TESTS = ("tests/**", "test/**", "**/tests/**", "**/test_*.py", "**/*_test.py", "**/*_test.go",
                 "**/*.test.*", "**/*.spec.*")
DEFAULT_CHANGES = "changes"
KEYS = {"diff-budget", "generated", "tests", "changes"}


@dataclass
class Config:
    max_lines: int | None = DEFAULT_LINES     # None: no limit
    max_files: int | None = DEFAULT_FILES
    generated: list[str] = field(default_factory=lambda: list(DEFAULT_GENERATED))
    tests: list[str] = field(default_factory=lambda: list(DEFAULT_TESTS))
    changes: str | None = DEFAULT_CHANGES     # None: no fragment rule
    source: str = "defaults"                  # where the settings came from, for the summary


def _variants(pattern: str) -> set[str]:
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


def matches(path: str, patterns: list[str]) -> bool:
    """gitignore-style: the last pattern that matches decides; `!glob` takes a path back out."""
    hit = False
    for p in patterns:
        neg = p.startswith("!")
        g = p[1:] if neg else p
        if any(fnmatch.fnmatchcase(path, v) for v in _variants(g)):
            hit = not neg
    return hit


def _globs(value: str) -> list[str]:
    return [] if value.strip().lower() == "none" else [g.strip() for g in value.split(",") if g.strip()]


def parse_config(text: str, source: str = CONFIG_FILE) -> tuple[Config, list[str]]:
    """The settings from the first ```work-system-pr block in `text`, and warnings for lines it can't use."""
    cfg, warnings = Config(source=f"defaults ({source} has no work-system-pr block)"), []
    m = re.search(r"(?ms)^[ \t]*```+[ \t]*work-system-pr[ \t]*\n(.*?)^[ \t]*```", text or "")
    if not m:
        return cfg, warnings
    cfg.source = source
    seen: dict[str, list[str]] = {}
    for raw in m.group(1).splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        k, sep, v = line.partition(":")
        k = k.strip().lower()
        if not sep or k not in KEYS:
            warnings.append(f"{source}: work-system-pr setting {line!r} is not one of {', '.join(sorted(KEYS))}")
            continue
        seen.setdefault(k, []).append(v.strip())
    for v in seen.get("diff-budget", []):
        if v.lower() == "none":
            cfg.max_lines = cfg.max_files = None
            continue
        parts = re.findall(r"(\d+)\s*(lines?|files?)\b", v, re.I)
        if not parts:
            warnings.append(f"{source}: diff-budget {v!r} should read like '500 lines, 25 files'; the default holds")
        for n, unit in parts:
            if unit.lower().startswith("line"):
                cfg.max_lines = int(n)
            else:
                cfg.max_files = int(n)
    for k in ("generated", "tests"):
        if k in seen:
            setattr(cfg, k, [g for v in seen[k] for g in _globs(v)])
    if "changes" in seen:
        v = seen["changes"][-1].strip().strip("/")
        cfg.changes = None if v.lower() == "none" or not v else v
    return cfg, warnings


def load_config(read_base: Callable[[], str] | None, files: list[dict] | None,
                read_checkout: Callable[[], str] | None = None) -> tuple[Config, list[str]]:
    """The settings at the PR's base commit. If that read fails, the checked-out AGENTS.md is used only when the PR
    leaves it unchanged; otherwise the defaults hold, with a warning."""
    why = "the PR event has no base commit"
    if read_base is not None:
        try:
            return parse_config(read_base(), f"{CONFIG_FILE} at the base commit")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return Config(source=f"defaults (no {CONFIG_FILE} at the base commit)"), []
            why = f"reading it at the base commit failed (HTTP {e.code})"
        except (urllib.error.URLError, OSError, ValueError, UnicodeDecodeError) as e:
            why = f"reading it at the base commit failed ({e})"
    unchanged = files is not None and CONFIG_FILE not in _paths(files)
    if read_checkout is not None and unchanged:
        try:
            cfg, warns = parse_config(read_checkout(), f"{CONFIG_FILE} in the checkout")
            return cfg, [f"{CONFIG_FILE} was read from the checkout because {why}; the PR does not change it", *warns]
        except (OSError, UnicodeDecodeError):
            pass
    return Config(source="defaults"), [f"the PR check's settings in {CONFIG_FILE} were not read because {why}; "
                                       "the defaults hold"]


def _paths(files: list[dict]) -> list[str]:
    out = []
    for f in files:
        out += [p for p in (f.get("filename"), f.get("previous_filename")) if p]
    return out


def _line(body: str, name: str) -> str | None:
    body = re.sub(r"(?s)<!--.*?(?:-->|\Z)", "", body or "")
    m = re.search(rf"(?mi)^[\s>*_-]*{re.escape(name)}:\s*(.*)$", body)
    return m.group(1).strip().strip("*_ ") if m else None


def _is_regen(pr: dict) -> bool:
    labels = {str(lab.get("name") or "") for lab in pr.get("labels") or []}
    if REGEN_LABEL in labels:
        return True
    head, base = pr.get("head") or {}, pr.get("base") or {}
    if head.get("ref") != REGEN_BRANCH:
        return False
    hrepo, brepo = (head.get("repo") or {}).get("full_name"), (base.get("repo") or {}).get("full_name")
    return not (hrepo and brepo and hrepo != brepo)  # a fork's bot/generated is not the regeneration PR


def _fragment(path: str, changes: str, key: str) -> bool:
    name = path[len(changes) + 1:] if path.startswith(changes + "/") else None
    return bool(name) and re.fullmatch(rf"{re.escape(key)}(\.[a-z]+)?\.md", name or "") is not None


def check_shape(pr: dict, files: list[dict] | None, cfg: Config, *, key: str | None) -> tuple[list[str], list[str]]:
    """Rule 8: (errors, warnings)."""
    errors: list[str] = []
    warnings: list[str] = []
    if files is None:
        return errors, ["could not list the PR's files, so the diff budget, generated files and changelog fragment "
                        "were not checked"]
    changes = cfg.changes
    in_changes = (lambda p: changes is not None and p.startswith(changes + "/"))
    # a release fold deletes fragments into CHANGELOG.md
    fold = changes is not None and "CHANGELOG.md" in _paths(files) and any(
        f.get("status") == "removed" and in_changes(f.get("filename") or "") for f in files)

    generated = sorted({p for p in _paths(files) if matches(p, cfg.generated)
                        and not (fold and p == "CHANGELOG.md")})
    if generated and not _is_regen(pr):
        shown = ", ".join(generated[:5]) + (f" and {len(generated) - 5} more" if len(generated) > 5 else "")
        errors.append(f"the PR edits generated files ({shown}); edit their sources instead, the build writes these "
                      f"after merge (only the {REGEN_BRANCH} PR or a PR labelled {REGEN_LABEL!r} commits them)")

    counted = [f for f in files if not matches(f.get("filename") or "", cfg.tests)
               and not in_changes(f.get("filename") or "") and not matches(f.get("filename") or "", cfg.generated)]
    lines = sum(int(f.get("additions") or 0) + int(f.get("deletions") or 0) for f in counted)
    over = []
    if cfg.max_lines is not None and lines > cfg.max_lines:
        over.append(f"{lines} changed lines (budget {cfg.max_lines})")
    if cfg.max_files is not None and len(counted) > cfg.max_files:
        over.append(f"{len(counted)} changed files (budget {cfg.max_files})")
    if over:
        reason = _line(pr.get("body") or "", "Budget")
        what = (f"the PR is over its diff budget: {' and '.join(over)}, not counting tests, changelog fragments or "
                f"generated files ({cfg.source})")
        if reason:
            warnings.append(f"{what}; accepted for the stated reason: {reason}")
        else:
            errors.append(f"{what}. Split it into smaller PRs, or add a 'Budget: <reason>' line to the body")

    if key and changes is not None and not fold and counted:
        if not any(_fragment(f.get("filename") or "", changes, key) and f.get("status") != "removed" for f in files):
            errors.append(f"the PR changes source but adds no changelog fragment: add {changes}/{key}.md (or "
                          f"{changes}/{key}.<kind>.md, such as {key}.fixed.md)")
    return errors, warnings
