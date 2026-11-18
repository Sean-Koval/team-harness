#!/usr/bin/env python3
"""SessionEnd hook: append one usage line per session to a local log, for cost per PR.

Claude Code passes the event as JSON on stdin, with `session_id`, `transcript_path` and `cwd`. This reads the usage
the transcript records on each model response (and on the session's subagent transcripts beside it, when there are
any) and appends one JSON line to the usage log:

    {"schema_version": 1, "session_id": "...", "ticket": "PROJ-123", "branch": "PROJ-123-slug", "repo": "owner/name",
     "models": ["claude-opus-5-5"], "requests": 12, "input_tokens": 51000, "output_tokens": 2300,
     "cache_read_input_tokens": 40000, "cache_creation_input_tokens": 9000, "cost_usd": 0.0731,
     "by_model": {"claude-opus-5-5": {"requests": 12, "input_tokens": ..., "cost_usd": 0.0731}},
     "started_at": "2026-11-18T14:00:00Z", "ended_at": "2026-11-18T14:20:00Z"}

`input_tokens`, `output_tokens` and `cost_usd` have the capture run log's meaning (ai-dlc `knowledge stats`):
`input_tokens` counts every prompt token, cache reads and writes included, and the two cache fields break it down.
`cost_usd` is estimated from `prices.json` beside this file; a model it does not list, or a rate it does not have,
makes the cost null, never a guess. The ticket key comes from the branch (`PROJ-123-slug`, or `feature/PROJ-123-slug`);
no key, `null`. The line holds counts, names and times only: no prompt, reply, file content or credential.

The log is `SESSION_USAGE_LOG` when set, else `usage.jsonl` under the user's data directory (`%LOCALAPPDATA%` on
Windows, `~/Library/Application Support` on macOS, `$XDG_DATA_HOME` or `~/.local/share` elsewhere), in a
`work-system` folder. A resumed session appends a line for what it spent since its last line, so the lines of one
session add up. It never blocks and prints nothing: any failure exits 0. Standard library only, so it runs natively on
Windows too.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1
LOG_ENV = "SESSION_USAGE_LOG"
PRICES = Path(__file__).resolve().with_name("prices.json")
KEY = re.compile(r"(?:^|/)([A-Z][A-Z0-9]{1,9}-[0-9]+)(?=$|[-_/.])")
LOG_TAIL_BYTES = 2_000_000  # how far back the log is read for this session's earlier lines
TOKENS = ("input_tokens", "output_tokens", "cache_read_input_tokens", "cache_creation_input_tokens")


def log_path() -> Path:
    if os.environ.get(LOG_ENV):
        return Path(os.environ[LOG_ENV])
    if os.name == "nt":
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData" / "Local")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "work-system" / "usage.jsonl"


def _int(v: object) -> int:
    return v if isinstance(v, int) and not isinstance(v, bool) and v > 0 else 0


def _time(v: object) -> datetime | None:
    if not isinstance(v, str):
        return None
    try:
        t = datetime.fromisoformat(v.replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _iso(t: datetime | None) -> str | None:
    return t.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ") if t else None


def responses(lines, since: datetime | None = None) -> tuple[dict[str, dict], dict]:
    """({response id: {model, usage, time}}, {branch, cwd, started, ended}). A response is written as one transcript
    line per content block, each with the same usage, so it is counted once (the last line wins)."""
    out: dict[str, dict] = {}
    meta: dict = {"branch": None, "cwd": None, "started": None, "ended": None}
    for line in lines:
        if '"usage"' not in line and '"gitBranch"' not in line:
            continue  # most lines carry neither; skip their parse
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if not isinstance(entry, dict):
            continue
        for k, field in (("branch", "gitBranch"), ("cwd", "cwd")):
            if isinstance(entry.get(field), str) and entry[field]:
                meta[k] = entry[field]
        message = entry.get("message")
        if entry.get("type") != "assistant" or not isinstance(message, dict):
            continue
        usage, model = message.get("usage"), message.get("model")
        if not isinstance(usage, dict) or not isinstance(model, str) or model.startswith("<"):
            continue  # "<synthetic>": a message the client wrote, not a model call
        when = _time(entry.get("timestamp"))
        if since is not None and (when is None or when <= since):
            continue
        rid = str(message.get("id") or entry.get("requestId") or entry.get("uuid") or len(out))
        out[rid] = {"model": model, "usage": usage, "time": when}
        if when is not None:
            meta["started"] = min(meta["started"] or when, when)
            meta["ended"] = max(meta["ended"] or when, when)
    return out, meta


def _rate(row: dict, name: str) -> float | None:
    v = row.get(name)
    return float(v) if isinstance(v, (int, float)) and not isinstance(v, bool) else None


def request_cost(model: str, usage: dict, prices: dict) -> float | None:
    """USD for one response, or None when the price table can't say."""
    row = (prices.get("models") or {}).get(re.sub(r"\[[^\]]*\]$", "", model))
    if not isinstance(row, dict) or usage.get("speed") not in (None, "standard"):
        return None  # an unknown model, or fast mode, which the table does not price
    fresh, out = _int(usage.get("input_tokens")), _int(usage.get("output_tokens"))
    read, write = _int(usage.get("cache_read_input_tokens")), _int(usage.get("cache_creation_input_tokens"))
    split = usage.get("cache_creation") if isinstance(usage.get("cache_creation"), dict) else {}
    w1h = min(_int(split.get("ephemeral_1h_input_tokens")), write)
    w5m = write - w1h
    above = row.get("above") if isinstance(row.get("above"), dict) else None
    if above and fresh + read + write > _int(above.get("prompt_tokens")):
        row = above
    total = 0.0
    for n, rate in ((fresh, "input"), (out, "output"), (read, "cache_read"), (w5m, "cache_write_5m"),
                    (w1h, "cache_write_1h")):
        if n:
            r = _rate(row, rate)
            if r is None:
                return None
            total += n * r
    return total / 1_000_000


def summarize(found: dict[str, dict], prices: dict) -> dict:
    by_model: dict[str, dict] = {}
    for r in found.values():
        u = r["usage"]
        m = by_model.setdefault(r["model"], {"requests": 0, **{k: 0 for k in TOKENS}, "cost_usd": 0.0})
        m["requests"] += 1
        fresh = _int(u.get("input_tokens"))
        read, write = _int(u.get("cache_read_input_tokens")), _int(u.get("cache_creation_input_tokens"))
        m["input_tokens"] += fresh + read + write
        m["output_tokens"] += _int(u.get("output_tokens"))
        m["cache_read_input_tokens"] += read
        m["cache_creation_input_tokens"] += write
        cost = request_cost(r["model"], u, prices)
        m["cost_usd"] = None if cost is None or m["cost_usd"] is None else m["cost_usd"] + cost
    for m in by_model.values():
        if m["cost_usd"] is not None:
            m["cost_usd"] = round(m["cost_usd"], 6)
    total = {k: sum(m[k] for m in by_model.values()) for k in ("requests", *TOKENS)}
    costs = [m["cost_usd"] for m in by_model.values()]
    total["cost_usd"] = None if any(c is None for c in costs) else round(sum(costs), 6)
    return {"models": sorted(by_model), **total, "by_model": by_model}


def ticket(branch: str | None) -> str | None:
    m = KEY.search(branch or "")
    return m.group(1) if m else None


def _git(cwd: str, *args: str) -> str | None:
    try:
        r = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, timeout=3,
                           stdin=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        return None
    return r.stdout.strip() if r.returncode == 0 and r.stdout.strip() else None


def repo_name(cwd: str | None) -> str | None:
    """`owner/name` from the origin remote (never its credentials), else the work tree's folder name."""
    if not cwd or not Path(cwd).is_dir():
        return None
    url = _git(cwd, "remote", "get-url", "origin")
    m = re.search(r"[:/]([^/:@\s]+/[^/:@\s]+?)(?:\.git)?/?$", url or "")
    if m:
        return m.group(1)
    top = _git(cwd, "rev-parse", "--show-toplevel")
    return Path(top).name if top else Path(cwd).name


def _session_lines(session_id: str) -> list[dict]:
    path = log_path()
    if not path.is_file():
        return []
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - LOG_TAIL_BYTES))
        lines = f.read().decode("utf-8", errors="replace").splitlines()
    out = []
    for line in lines[1:] if size > LOG_TAIL_BYTES else lines:
        try:
            entry = json.loads(line)
        except ValueError:
            continue
        if isinstance(entry, dict) and entry.get("session_id") == session_id:
            out.append(entry)
    return out


def transcripts(path: Path, session_id: str) -> list[Path]:
    """The session's transcript and its subagents' (`<session id>/subagents/*.jsonl` beside it)."""
    sub = path.parent / session_id / "subagents"
    return [path, *sorted(sub.glob("*.jsonl"))] if session_id and sub.is_dir() else [path]


def build_line(event: dict, prices: dict) -> dict | None:
    path = Path(str(event.get("transcript_path") or ""))
    if not path.is_file():
        return None
    session_id = str(event.get("session_id") or path.stem)
    ends = [_time(e.get("ended_at")) for e in _session_lines(session_id)]
    since = max((t for t in ends if t is not None), default=None)
    found: dict[str, dict] = {}
    meta: dict = {}
    for p in transcripts(path, session_id):
        with p.open(encoding="utf-8", errors="replace") as f:
            got, m = responses(f, since)
        found.update(got)
        if p == path:
            meta = m
        else:  # a subagent's responses widen the session's time span
            for k, pick in (("started", min), ("ended", max)):
                if m[k] is not None:
                    meta[k] = pick(meta[k] or m[k], m[k])
    if not found:
        return None  # nothing spent (or nothing new since this session's last line)
    cwd = meta.get("cwd") or event.get("cwd")
    branch = meta.get("branch") or (_git(str(cwd), "rev-parse", "--abbrev-ref", "HEAD") if cwd else None)
    if branch == "HEAD":
        branch = None  # detached
    return {"schema_version": SCHEMA_VERSION, "session_id": session_id, "ticket": ticket(branch), "branch": branch,
            "repo": repo_name(str(cwd) if cwd else None), **summarize(found, prices),
            "started_at": _iso(meta.get("started")), "ended_at": _iso(meta.get("ended"))}


def main() -> int:
    try:
        # bytes, not sys.stdin: on Windows its text layer decodes with the console code page (knowledge_session_end.py)
        event = json.loads(sys.stdin.buffer.read().decode("utf-8-sig") or "{}")
        try:
            prices = json.loads(PRICES.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            prices = {}  # no table: every cost is null, the tokens still count
        line = build_line(event if isinstance(event, dict) else {}, prices if isinstance(prices, dict) else {})
        if line is None:
            return 0
        out = log_path()
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("a", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(line, sort_keys=True) + "\n")
    except Exception:  # usage is never worth failing the session's end
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
