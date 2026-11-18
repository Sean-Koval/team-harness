"""KAN-514: the SessionEnd usage hook writes one line per session, counted by hand from a fixture transcript."""

import importlib.util
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / "shared/work-system/hooks/usage_session_end.py"
PRICES = ROOT / "shared/work-system/hooks/prices.json"
FIXTURE = ROOT / "tests/fixtures/usage-hook"
sys.path.insert(0, str(ROOT / "scripts"))
import install_local as il  # noqa: E402

spec = importlib.util.spec_from_file_location("usage_session_end", HOOK)
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)

SESSION = "s-1"


def session(tmp_path: Path, subagent: bool = True) -> Path:
    t = tmp_path / "projects" / f"{SESSION}.jsonl"
    t.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURE / "session.jsonl", t)
    if subagent:
        sub = t.parent / SESSION / "subagents"
        sub.mkdir(parents=True)
        shutil.copyfile(FIXTURE / "subagent.jsonl", sub / "agent-a1.jsonl")
    return t


def run(transcript: Path, log: Path, event: dict | None = None, stdin: bytes | None = None):
    ev = {"hook_event_name": "SessionEnd", "session_id": SESSION, "transcript_path": str(transcript), **(event or {})}
    env = {**os.environ, hook.LOG_ENV: str(log)}
    return subprocess.run([sys.executable, str(HOOK)], input=stdin if stdin is not None else json.dumps(ev).encode(),
                          capture_output=True, env=env, timeout=30)


def lines(log: Path) -> list[dict]:
    return [json.loads(x) for x in log.read_text(encoding="utf-8").splitlines()] if log.is_file() else []


def test_one_line_matches_the_hand_count(tmp_path):
    log = tmp_path / "usage.jsonl"
    r = run(session(tmp_path), log)
    assert r.returncode == 0 and r.stdout == b"" and r.stderr == b""
    [line] = lines(log)
    # msg_1 (two content-block lines, one response), msg_2 (5m and 1h cache writes), the subagent's msg_4;
    # the <synthetic> message and the unparseable line don't count
    assert line["requests"] == 3
    assert line["input_tokens"] == (100 + 1000 + 200) + (10 + 1200 + 300) + 2000 == 4810
    assert line["output_tokens"] == 50 + 400 + 100
    assert line["cache_read_input_tokens"] == 1000 + 1200
    assert line["cache_creation_input_tokens"] == 200 + 300
    opus = (100 * 4 + 50 * 20 + 1000 * 0.2 + 200 * 5) + (10 * 4 + 400 * 20 + 1200 * 0.2 + 100 * 5 + 200 * 8)
    haiku = 2000 * 0.1 + 100 * 0.5
    assert line["by_model"]["claude-opus-5-5"]["cost_usd"] == pytest.approx(opus / 1e6)
    assert line["by_model"]["claude-haiku-5-5"]["cost_usd"] == pytest.approx(haiku / 1e6)
    assert line["cost_usd"] == pytest.approx((opus + haiku) / 1e6)
    assert line["models"] == ["claude-haiku-5-5", "claude-opus-5-5"]
    assert (line["ticket"], line["branch"], line["session_id"]) == ("KAN-514", "KAN-514-usage-hook", SESSION)
    assert (line["started_at"], line["ended_at"]) == ("2026-11-18T14:00:05Z", "2026-11-18T14:20:00Z")
    assert line["schema_version"] == 1 and line["repo"] is None  # the fixture's cwd does not exist


def test_the_line_has_the_capture_run_logs_usage_fields(tmp_path):
    # ai-dlc knowledge stats reads input_tokens, output_tokens and cost_usd (null: unknown) from the capture run log
    log = tmp_path / "usage.jsonl"
    run(session(tmp_path), log)
    [line] = lines(log)
    assert {"input_tokens", "output_tokens", "cost_usd", "started_at", "ended_at", "schema_version"} <= set(line)
    assert all(isinstance(line[k], int) for k in hook.TOKENS)


def test_no_transcript_text_file_contents_or_credentials(tmp_path):
    log = tmp_path / "usage.jsonl"
    run(session(tmp_path), log)
    text = log.read_text(encoding="utf-8")
    for secret in ("SECRET-TOKEN-123", "config.py", "def secret", "hunter2", "second block", "No response"):
        assert secret not in text
    keys = set(lines(log)[0])
    assert keys == {"schema_version", "session_id", "ticket", "branch", "repo", "models", "requests", *hook.TOKENS,
                    "cost_usd", "by_model", "started_at", "ended_at"}


def test_repo_comes_from_origin_without_its_credentials(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    git = ["git", "-C", str(work)]
    subprocess.run([*git, "init", "-q"], check=True)
    subprocess.run([*git, "remote", "add", "origin", "https://user:tok-123@github.com/acme/widgets.git"], check=True)
    assert hook.repo_name(str(work)) == "acme/widgets"
    subprocess.run([*git, "remote", "set-url", "origin", "git@github.com:acme/gadgets.git"], check=True)
    assert hook.repo_name(str(work)) == "acme/gadgets"
    subprocess.run([*git, "remote", "remove", "origin"], check=True)
    assert hook.repo_name(str(work)) == "work"


@pytest.mark.parametrize("branch, key", [("KAN-514-usage-hook", "KAN-514"), ("feature/KAN-7-x", "KAN-7"),
                                         ("KAN-12", "KAN-12"), ("claude/wizardly-pascal", None), ("main", None),
                                         ("KAN-514x", None), (None, None)])
def test_ticket_key_from_the_branch(branch, key):
    assert hook.ticket(branch) == key


def test_an_unknown_model_or_rate_costs_null_never_a_guess():
    prices = json.loads(PRICES.read_text(encoding="utf-8"))
    u = {"input_tokens": 10, "output_tokens": 10}
    assert hook.request_cost("claude-unknown-9", u, prices) is None
    assert hook.request_cost("claude-opus-5-5", {**u, "speed": "fast"}, prices) is None
    big = {"input_tokens": 150_000, "output_tokens": 10}
    assert hook.request_cost("claude-haiku-5-5", big, prices) == pytest.approx((150_000 * 0.5 + 10 * 2.5) / 1e6)
    # above 100K the table has no cache rate for Haiku, so a request with cache reads there is unknown
    assert hook.request_cost("claude-haiku-5-5", {**big, "cache_read_input_tokens": 5}, prices) is None
    found = {"a": {"model": "claude-unknown-9", "usage": u, "time": None},
             "b": {"model": "claude-opus-5-5", "usage": u, "time": None}}
    s = hook.summarize(found, prices)
    assert s["cost_usd"] is None and s["by_model"]["claude-opus-5-5"]["cost_usd"] is not None
    assert s["input_tokens"] == 20  # tokens still count
    assert hook.summarize(found, {})["cost_usd"] is None  # no price table at all


def test_every_price_row_is_complete():
    prices = json.loads(PRICES.read_text(encoding="utf-8"))
    for model, row in prices["models"].items():
        assert all(isinstance(row.get(k), float) for k in
                   ("input", "output", "cache_read", "cache_write_5m", "cache_write_1h")), model
        assert row["cache_write_5m"] == pytest.approx(row["input"] * 1.25), model
        assert row["cache_write_1h"] == pytest.approx(row["input"] * 2), model


def test_a_resumed_session_adds_only_what_it_spent_since(tmp_path):
    log = tmp_path / "usage.jsonl"
    t = session(tmp_path)
    run(t, log)
    run(t, log)  # ended again with nothing new: no line
    assert len(lines(log)) == 1
    with t.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps({"type": "assistant", "gitBranch": "KAN-514-usage-hook", "timestamp": "2026-11-18T15:00:00Z",
                            "message": {"id": "msg_9", "model": "claude-opus-5-5",
                                        "usage": {"input_tokens": 7, "output_tokens": 3}}}) + "\n")
    run(t, log)
    first, second = lines(log)
    assert (second["requests"], second["input_tokens"], second["output_tokens"]) == (1, 7, 3)
    assert second["started_at"] == "2026-11-18T15:00:00Z" and first["requests"] == 3


@pytest.mark.parametrize("stdin", [b"", b"not json", b"[]", json.dumps({"transcript_path": "/nope.jsonl"}).encode()])
def test_never_blocks_and_prints_nothing(tmp_path, stdin):
    log = tmp_path / "usage.jsonl"
    r = run(tmp_path / "unused.jsonl", log, stdin=stdin)
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"") and not log.exists()


def test_an_unwritable_log_still_exits_0(tmp_path):
    blocker = tmp_path / "file"
    blocker.write_text("x")
    r = run(session(tmp_path), blocker / "usage.jsonl")
    assert (r.returncode, r.stdout, r.stderr) == (0, b"", b"")


def test_default_log_is_under_the_users_data_dir(monkeypatch, tmp_path):
    monkeypatch.delenv(hook.LOG_ENV, raising=False)
    path = hook.log_path()
    assert path.name == "usage.jsonl" and path.parent.name == "work-system"
    if os.name == "nt":
        assert "AppData" in str(path) or os.environ.get("LOCALAPPDATA", "?") in str(path)
    elif sys.platform == "darwin":
        assert "Application Support" in str(path)
    else:
        monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
        assert hook.log_path() == tmp_path / "work-system" / "usage.jsonl"


HARNESSES = ("suite-default", "work-default")
COMMAND = 'python3 "$HOME/.claude/hooks/usage_session_end.py"'


@pytest.mark.parametrize("h", HARNESSES)
def test_rendered_and_registered_with_its_price_table(h):
    hd = ROOT / "harnesses" / h / "native/claude-code"
    assert (hd / "hooks" / HOOK.name).read_bytes() == HOOK.read_bytes()
    assert (hd / "hooks" / PRICES.name).read_bytes() == PRICES.read_bytes()
    settings = json.loads((hd / "settings.json").read_text(encoding="utf-8"))
    assert COMMAND in [x["command"] for e in settings["hooks"]["SessionEnd"] for x in e["hooks"]]


def _installed(home: Path, h: str) -> None:
    shutil.copytree(ROOT / "harnesses" / h / "native/claude-code/hooks", home / ".claude" / "hooks")


@pytest.mark.skipif(shutil.which("sh") is None or os.name == "nt", reason="needs a POSIX sh")
@pytest.mark.parametrize("h", HARNESSES)
def test_installed_command_writes_the_line_in_sh(h, tmp_path):
    home, log = tmp_path / "home", tmp_path / "usage.jsonl"
    _installed(home, h)
    event = json.dumps({"session_id": SESSION, "transcript_path": str(session(tmp_path))})
    r = subprocess.run(["sh", "-c", COMMAND], input=event, capture_output=True, encoding="utf-8", timeout=30,
                       env={**os.environ, "HOME": str(home), hook.LOG_ENV: str(log)})
    assert (r.returncode, r.stdout, r.stderr) == (0, "", "")
    [line] = lines(log)
    assert line["requests"] == 3 and line["cost_usd"] is not None  # prices.json found beside the installed hook


@pytest.mark.skipif(os.name != "nt", reason="the native Windows hook shells")
@pytest.mark.parametrize("shell", ["git-bash", "powershell"])
@pytest.mark.parametrize("h", HARNESSES)
def test_installed_command_writes_the_line_in_windows_hook_shells(h, shell, tmp_path, monkeypatch):
    if shell == "git-bash" and il._git_bash() is None:
        pytest.skip("no Git Bash on this machine")
    if shell == "powershell":
        monkeypatch.setattr(il, "_git_bash", lambda: None)
    monkeypatch.setattr(il, "WINDOWS", True)
    home = tmp_path / "Jörg Ñúñez"  # a profile path with letters outside the console code page
    _installed(home, h)
    log = home / "usage.jsonl"
    native = il._hook_command(COMMAND, "user", ROOT / "harnesses" / h, home / ".claude")
    event = json.dumps({"session_id": SESSION, "transcript_path": str(session(home))})
    r = subprocess.run(il.hook_shell(native), input=event.encode("utf-8"), capture_output=True, timeout=60,
                       env={**os.environ, "HOME": str(home), "USERPROFILE": str(home), hook.LOG_ENV: str(log)})
    assert r.returncode == 0, f"{native}\n{(r.stderr or r.stdout).decode('utf-8', 'replace')}"
    [line] = lines(log)
    assert line["requests"] == 3 and line["cost_usd"] is not None
