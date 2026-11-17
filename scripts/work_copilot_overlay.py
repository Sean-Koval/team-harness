"""Work Copilot's config from the company org overlay (KAN-381).

The org overlay (`orgs/<org>/org.yaml`, the harness's `org:` in shared/work-system/targets.yaml) already sets the work
site, the Jira project and the review room for the work-system skills. Work Copilot needs the same three values. This
script renders them as Work Copilot's overlay file, so one file feeds both instead of two hand-edited ones:

    python scripts/work_copilot_overlay.py --harness work-default --out work-copilot-overlay.json
    work-copilot overlay apply work-copilot-overlay.json

`work-copilot doctor` then reports which overlay is applied. The file holds only what org.yaml holds: no credentials.
A placeholder org (placeholder: true, the public example) renders with `placeholder: true`, and Work Copilot reports
it as not applied.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sync_shared  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "work-copilot.overlay/v1"


def overlay(org: dict, where: str) -> dict:
    """Work Copilot's overlay for a valid org.yaml; ValueError naming every problem otherwise."""
    problems = sync_shared.validate_org(org, where)
    if problems:
        raise ValueError("\n".join(problems))
    params = org.get("params") or {}
    work = next((t for t in org["ticket_types"] if t.get("role") == "work"), None)
    out = {"schema": SCHEMA, "name": org["name"], "placeholder": bool(org.get("placeholder", False)), "source": where}
    values = {"work_site": params.get("kb_site"), "kb_space": params.get("kb_space"),
              "jira_project": work["project"] if work else None,
              "room": (org.get("review_request") or {}).get("room")}
    return out | {k: v for k, v in values.items() if v}


def org_for(root: Path, harness: str) -> str | None:
    """The harness's `org:` from targets.yaml (a path from the repository root), or None."""
    targets = yaml.safe_load((root / "shared/work-system/targets.yaml").read_text(encoding="utf-8")) or {}
    entry = (targets.get("harnesses") or {}).get(harness) or {}
    return (entry.get("org") or "").rstrip("/") or None


def render(root: Path, *, harness: str | None = None, org: str | None = None) -> dict:
    rel = org.rstrip("/") if org else org_for(root, harness or "")
    if not rel:
        raise ValueError(f"{harness} names no org overlay in shared/work-system/targets.yaml")
    d = (root / rel).resolve()
    if not d.is_relative_to((root / "orgs").resolve()) or not (d / "org.yaml").is_file():
        raise ValueError(f"{rel} must be a directory under orgs/ with an org.yaml")
    where = f"{rel}/org.yaml"
    return overlay(yaml.safe_load((d / "org.yaml").read_text(encoding="utf-8")), where)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    which = ap.add_mutually_exclusive_group(required=True)
    which.add_argument("--harness", help="the harness whose org overlay to render (its org: in targets.yaml)")
    which.add_argument("--org", help="an org directory, such as orgs/example-co")
    ap.add_argument("--out", type=Path, help="write the overlay here (default: print it)")
    a = ap.parse_args(argv)
    try:
        data = render(ROOT, harness=a.harness, org=a.org)
    except (OSError, ValueError, yaml.YAMLError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    text = json.dumps(data, indent=2, ensure_ascii=False) + "\n"
    if a.out:
        a.out.write_text(text, encoding="utf-8")
        print(f"wrote {a.out}; now run: work-copilot overlay apply {a.out}")
    else:
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
