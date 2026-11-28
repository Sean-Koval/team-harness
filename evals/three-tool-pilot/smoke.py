# /// script
# requires-python = ">=3.12"
# dependencies = [
#   "ai-dlc @ git+https://github.com/Sean-Koval/ai-dlc.git@a51244c9468e1f75b87582f3a59805c9b0e2ab26",
#   "work-copilot @ git+https://github.com/Sean-Koval/work-copilot.git@3ca58410d89118ce6b41d194bede848ac6032afb",
#   "PyYAML>=6,<7",
# ]
# ///
"""Run the three-tool pilot against local fictional data and temporary configuration."""

import argparse
import asyncio
from contextlib import contextmanager
from datetime import timedelta
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
import yaml

HERE = Path(__file__).resolve().parent
HARNESS = HERE.parents[1]
FIXTURE = HERE / "fixture"
TICKET = "PILOT-1"
DECISION = "Decided: azurite banners trim surrounding name whitespace unless verbatim mode is requested."


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def run(cwd, env, *args, expected=0, include_stderr=False):
    result = subprocess.run(args, cwd=cwd, env=env, capture_output=True, text=True, timeout=60)
    if result.returncode != expected:
        raise RuntimeError(
            f"{' '.join(map(str, args))} exited {result.returncode}, expected {expected}\n"
            f"{result.stdout}{result.stderr}"
        )
    return result.stdout + result.stderr if include_stderr else result.stdout


def local_environment(root):
    home = root / "home"
    home.mkdir()
    env = {name: os.environ[name] for name in ("PATH", "SYSTEMROOT", "WINDIR") if name in os.environ}
    env.update(
        HOME=str(home),
        USERPROFILE=str(home),
        APPDATA=str(home / "appdata"),
        LOCALAPPDATA=str(home / "localappdata"),
        XDG_CONFIG_HOME=str(home / "config"),
        XDG_DATA_HOME=str(home / "data"),
        XDG_CACHE_HOME=str(home / "cache"),
        CODEX_HOME=str(home / "codex"),
        GIT_CONFIG_NOSYSTEM="1",
        GIT_TERMINAL_PROMPT="0",
        PYTHONUTF8="1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    return env


async def copilot_session(copilot, root, env, state, *, vault=None, source_id=None):
    child_env = dict(env)
    if vault is not None:
        child_env["WORK_COPILOT_VAULT"] = str(vault)
    parameters = StdioServerParameters(
        command=str(copilot),
        args=["--data-dir", str(state), "--timezone", "UTC", "mcp"],
        cwd=str(root),
        env=child_env,
    )
    with (root / "mcp.log").open("a", encoding="utf-8") as log:
        async with stdio_client(parameters, errlog=log) as streams:
            async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=20)) as session:
                await session.initialize()

                async def call(tool, arguments):
                    result = await session.call_tool(tool, arguments)
                    require(not result.isError, f"{tool} failed: {result.content}")
                    return json.loads(result.content[0].text)

                if vault is not None:
                    receipt = await call("capture_note", {
                        "title": f"{TICKET} fictional banner decision",
                        "body": f">> {TICKET} {DECISION}\nUnmarked fictional private line.",
                        "project_id": "banner",
                    })
                    require(len(receipt["source_ids"]) == 1, "Expected one captured source")
                    return receipt["source_ids"][0]

                hits = await call("search_context", {"query": "azurite", "project_id": "banner"})
                if source_id is None:
                    require(hits == [], "An independent data directory returned a decision")
                    return
                require([hit["id"] for hit in hits] == [source_id], "Restart did not recover the same source")
                source = await call("get_source", {"source_id": source_id})
                require(source["revision"] == hits[0]["revision"], "Source revision disagrees with search")
                require(DECISION in source["body"], "Decision text missing from cited source")
                miss = await call("search_context", {"query": "azurite", "project_id": "unrelated"})
                require(miss == [], "Project filter returned unrelated evidence")
                return source


def exercise_copilot(root, env, repo, copilot, aidlc):
    state, vault = root / "copilot", root / "vault"
    wc = (copilot, "--data-dir", str(state), "--timezone", "UTC")
    run(root, env, *wc, "init", "--wizard", "--vault", str(vault),
        "--project-id", "banner", "--project-name", "Fictional banner")

    async def exercise_mcp():
        source_id = await copilot_session(copilot, root, env, state, vault=vault)
        source = await copilot_session(copilot, root, env, state, source_id=source_id)
        await copilot_session(copilot, root, env, root / "empty-copilot")
        return source

    observed_source = asyncio.run(exercise_mcp())

    knowledge = root / "knowledge"
    knowledge.mkdir()
    config = knowledge / "knowledge.toml"
    config.write_text("[format]\nversion = 1\n\n[transcripts]\ncustomers = []\n", encoding="utf-8")
    exported = json.loads(run(root, env, *wc, "export", "--to", str(knowledge),
                              "--owner", "fictional-pilot", "--scope", "team"))
    require(len(exported["written"]) == 1 and len(exported["raw_written"]) == 1,
            f"Expected one Source with raw evidence: {exported}")
    raw_path = knowledge / "inbox" / "raw" / exported["raw_written"][0]
    governed_line = raw_path.read_text(encoding="utf-8").strip()
    require(governed_line == f"{TICKET} {DECISION}", "Source export included unmarked text or lost the decision")
    source_lines = [re.sub(r"^L\d+: ", "", line) for line in observed_source["body"].splitlines()]
    require(f">> {governed_line}" in source_lines, "Exported line differs from the recalled source")
    report = json.loads(run(root, env, aidlc, "knowledge", "check", str(knowledge / "inbox"),
                            "--config", str(config), "--json"))
    require(report["status"] == "valid" and report["records"] == 1 and report["failures"] == [],
            f"AI-DLC did not validate one exported Source: {report}")
    source_record = knowledge / "inbox" / exported["written"][0]
    frontmatter = yaml.safe_load(source_record.read_text(encoding="utf-8").split("---\n", 2)[1])
    require(
        observed_source["id"] in {citation["id"] for citation in frontmatter["sources"]},
        "Export lost the original source ID",
    )

    async def check_over_mcp():
        parameters = StdioServerParameters(
            command=str(aidlc), args=["mcp", "serve", "--root", str(repo)],
            cwd=str(repo), env={**env, "KNOWLEDGE_REPO": str(knowledge)},
        )
        with (root / "mcp.log").open("a", encoding="utf-8") as log:
            async with stdio_client(parameters, errlog=log) as streams:
                async with ClientSession(*streams, read_timeout_seconds=timedelta(seconds=20)) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "knowledge_check", {"records": str(knowledge / "inbox")},
                    )
                    require(not result.isError, f"AI-DLC MCP knowledge check failed: {result.content}")
                    report = json.loads(result.content[0].text)
                    require(report["records"] == 1 and report["failures"] == [],
                            f"AI-DLC MCP did not validate one Source: {report}")

    asyncio.run(check_over_mcp())
    print("PASS Work Copilot decision survived restart, respected project/data-directory filters, and exported one Source validated by AI-DLC CLI and MCP.", flush=True)
    return governed_line, observed_source["id"], observed_source["revision"]


@contextmanager
def installed_harness(root, env, repo, *, built_candidate):
    python = sys.executable
    install = (
        python, HARNESS / "scripts" / "install_local.py",
        HARNESS / "harnesses" / "work-default", "--scope", "project", "--channel", "candidate",
    )
    if built_candidate:
        install += ("--allow-dirty",)
    run(repo, env, *install, "--apply")
    try:
        report = run(repo, env, *install, "--check")
        require("clean: work-default@candidate" in report, f"Expected a clean candidate install: {report}")

        skill = repo / ".claude" / "skills" / "implement-standard" / "SKILL.md"
        intake = skill.parent / "scripts" / "intake.py"
        installed_text = skill.read_bytes()
        digest = hashlib.sha256(installed_text).hexdigest()
        prompt_command = (python, "-c", "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())")
        issue = root / "issue.json"
        for labels in (["standards-change"], []):
            issue.write_text(json.dumps({"key": TICKET, "fields": {"labels": labels}}), encoding="utf-8")
            prompt = run(repo, env, python, intake, "run", issue, "--", *prompt_command)
            require(f"Read Jira issue {TICKET}" in prompt, "Intake omitted the canonical issue key")
            if labels:
                require(f"sha256={digest}" in prompt and prompt.endswith(installed_text.decode("utf-8")),
                        "Labelled intake did not carry the installed skill and digest")
            else:
                require("sha256=" not in prompt and "Team Harness intake" not in prompt,
                        "Routine intake unexpectedly got the standards skill")

        skill.write_bytes(installed_text + b"\nFictional drift.\n")
        try:
            drift = run(repo, env, *install, "--check", expected=1)
            require("edited: skills/implement-standard/SKILL.md" in drift,
                    f"Drift check missed the changed skill: {drift}")
        finally:
            skill.write_bytes(installed_text)

        manifest = json.loads((repo / ".claude" / "team-harness.json").read_text(encoding="utf-8"))
        channels = yaml.safe_load((HARNESS / "channels.yaml").read_text(encoding="utf-8"))
        require(manifest["harness_digest"] == channels["work-default"]["candidate"],
                "Installed harness digest differs from the candidate channel")
        print(f"Work-default candidate r{manifest['revision']} {manifest['harness_digest']}", flush=True)
        print("PASS Team Harness installed the candidate, injected the hashed skill only for the labelled issue, and detected edited guidance.", flush=True)
        yield
    finally:
        run(repo, env, *install, "--uninstall")
    require(not (repo / ".claude" / "skills" / "implement-standard").exists(),
            "Uninstall left the installed skill behind")
    require(run(repo, env, "git", "status", "--porcelain") == "", "Uninstall left changes in the seed checkout")


def exercise_work(repo, env, aidlc, evidence):
    governed_line, source_id, revision = evidence
    change = repo / "openspec" / "changes" / "format-names"
    shutil.copytree(FIXTURE / "openspec", repo / "openspec")
    proposal = change / "proposal.md"
    citation = f"Source `{source_id}`, revision `{revision}`."
    proposal.write_text(
        f"# {TICKET} banner whitespace\n\n> {governed_line}\n\n"
        f"{citation} See [banner spec](specs/banner/spec.md).\n",
        encoding="utf-8",
    )
    work = repo / ".ai-dlc" / "work" / "format-names.toml"
    work.parent.mkdir(parents=True)
    shutil.copyfile(FIXTURE / "format-names.toml", work)
    for name in ("ai-dlc.toml", "banner.py", "test_banner.py"):
        shutil.copyfile(FIXTURE / name, repo / name)

    run(repo, env, "git", "add", "--", "ai-dlc.toml", ".ai-dlc/work", "openspec", "banner.py", "test_banner.py")
    run(repo, env, "git", "-c", "user.email=pilot@example.invalid", "-c", "user.name=Fictional Pilot",
        "commit", "--quiet", "-m", f"{TICKET}: Track banner work and cited specification")
    validate = (aidlc, "work", "validate", "--all")
    report = json.loads(run(repo, env, *validate))
    require(report["valid"] is True and report["records"] == ["format-names"],
            f"AI-DLC did not validate the named work record: {report}")

    def citation_matches():
        saved = proposal.read_text(encoding="utf-8")
        return f"> {governed_line}" in saved.splitlines() and citation in saved

    require(citation_matches(), "The linked proposal must cite the exported decision and revision")
    cited_proposal = proposal.read_bytes()
    proposal.write_text(proposal.read_text(encoding="utf-8").replace(citation, ""), encoding="utf-8")
    try:
        require(not citation_matches(), "Removing the source citation passed the proposal evidence check")
    finally:
        proposal.write_bytes(cited_proposal)

    test = (sys.executable, "-m", "unittest", "-v", "test_banner")
    run(repo, env, *test)
    product = repo / "banner.py"
    good_product = product.read_text(encoding="utf-8")
    product.write_text(good_product.replace("args.name.strip()", "args.name"), encoding="utf-8")
    try:
        test_output = run(repo, env, *test, expected=1, include_stderr=True)
        require(
            "FAIL: test_default_trims_padding" in test_output
            and "test_verbatim_preserves_padding (test_banner.BannerTests.test_verbatim_preserves_padding) ... ok" in test_output,
            f"Regression did not fail the default while preserving the exception:\n{test_output}",
        )
    finally:
        product.write_text(good_product, encoding="utf-8")
    run(repo, env, *test)

    moved = repo / "format-names-moved"
    change.rename(moved)
    try:
        broken = json.loads(run(repo, env, *validate, expected=1))
        require(broken["valid"] is False and "Referenced local artifact is absent" in json.dumps(broken),
                f"AI-DLC did not identify the missing linked specification: {broken}")
    finally:
        moved.rename(change)
    print("PASS AI-DLC caught the missing linked spec; the banner check distinguished the default regression and allowed verbatim exception.", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--built-candidate", action="store_true",
        help="Use the lock-matching candidate already built and drift-checked in a CI checkout.",
    )
    args = parser.parse_args()
    bin_directory = Path(sys.executable).parent
    copilot = bin_directory / ("work-copilot.exe" if os.name == "nt" else "work-copilot")
    aidlc = bin_directory / ("ai-dlc.exe" if os.name == "nt" else "ai-dlc")
    with tempfile.TemporaryDirectory(prefix="three-tool-pilot-") as temporary:
        root = Path(temporary).resolve()
        env = local_environment(root)
        env["PATH"] = str(bin_directory) + os.pathsep + env.get("PATH", "")
        repo = root / "repo"
        repo.mkdir()
        run(repo, env, "git", "init", "--quiet")
        starter_files = {
            repo / "README.md": b"Fictional banner pilot.\n",
            repo / ".gitignore": b"/.claude/settings.local.json\n",
            repo / ".claude" / "settings.json": b'{"permissions":{"allow":["Bash(make product-check)"]}}\r\n',
            repo / ".claude" / "settings.local.json": b'{"permissions":{"allow":["Bash(make local-check)"]}}\n',
            Path(env["HOME"]) / ".claude" / "settings.json": b'{"permissions":{"allow":["Bash(make personal-check)"]}}\n',
        }
        for path, content in starter_files.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
        run(repo, env, "git", "add", "README.md", ".gitignore", ".claude/settings.json")
        run(repo, env, "git", "-c", "user.email=pilot@example.invalid", "-c", "user.name=Fictional Pilot",
            "commit", "--quiet", "-m", "Seed fictional pilot")
        with installed_harness(root, env, repo, built_candidate=args.built_candidate):
            evidence = exercise_copilot(root, env, repo, copilot, aidlc)
            exercise_work(repo, env, aidlc, evidence)
        for path, content in starter_files.items():
            require(path.read_bytes() == content, f"Uninstall modified the starter file {path}")
        print("PASS Team Harness uninstall preserved tracked, ignored, and personal starter files.", flush=True)
    print("PASS Temporary fixtures removed. This run covers local commands and stdio MCP.")


if __name__ == "__main__":
    main()
