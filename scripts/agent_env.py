#!/usr/bin/env python3
"""Start the agent environment (environments/agent.yaml) on this computer, the way hangar starts it in the cloud.

The spec is the one definition; hangar renders and runs it remotely. This script does the local half with hangar's
own code, so the two can't drift: hangar's renderer builds the image (`envspec.render`, the same Dockerfile and
context a hangar build gets, with the harness baked in since there are no pack mounts here), and hangar's
`egress.resolve` decides the allowlist that scripts/egress_proxy.py then enforces from a sidecar. The agent container:

- mounts nothing from the host: no home directory, no checkout, no socket;
- gets only the variables named in environments/agent.env.example, taken from this process's environment;
- reaches the internet only through the sidecar, on an internal Docker network (a tool that skips the proxy fails);
- clones its inputs from git (CODE_REPO to /workspace/code, KNOWLEDGE_REPO to /workspace/knowledge) and runs
  `ai-dlc doctor` on them.

    make agent-env                       # = python scripts/agent_env.py up: build, start, clone, doctor
    python scripts/agent_env.py report   # the pins and doctor, again, in the running instance
    python scripts/agent_env.py exec -- claude
    python scripts/agent_env.py check    # the acceptance checks: two fresh instances, no mounts, egress refused
    python scripts/agent_env.py down

It needs Docker and hangar (the Makefile runs it with the hangar commit CI pins). `--extra-ca FILE` adds a CA to the
image, for a network that intercepts TLS (hangar's own `extra_ca`). `pin_problems` is also run by
scripts/check_registry.py in CI.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parent.parent
ENV_NAME = "agent"
CONTRACT = ROOT / "environments" / "agent.env.example"
INPUTS = ("TICKET_KEY", "CODE_REPO", "KNOWLEDGE_REPO")
PINS = ("AGENT_ENV_HARNESS", "AGENT_ENV_HARNESS_DIGEST", "AI_DLC_REF", "KNOWLEDGE_FORMAT_VERSION")
PROXY_IMAGE = "python:3.12-slim"
PROXY_PORT = 3128
LABEL = "team-harness.agent-env"
MACHINE_TOML = """schema = 4

[paths]
vault = "/workspace/knowledge"

[target]
name = "local"
headless = true

[credentials.github]
source = "environment"
variable = "GH_TOKEN"
"""


# ------------------------------------------------------------------------------------------------ the definition
def catalog(root: Path = ROOT):
    from hangar import harness_lock as hl
    from hangar.envspec import EnvCatalog

    harness_dirs = sorted(d for d in (root / "harnesses").iterdir() if (d / hl.LOCK_FILE).is_file())
    return EnvCatalog([*harness_dirs, root / "environments" / "roles", root / "environments"])


def contract_names(path: Path = CONTRACT) -> list[str]:
    """The variable names agent.env.example declares, in order."""
    names = []
    for line in path.read_text().splitlines():
        m = re.match(r"^([A-Z][A-Z0-9_]*)=", line)
        if m:
            names.append(m.group(1))
    return names


def pin_problems(root: Path = ROOT) -> list[str]:
    """Where the spec's pins disagree with what they name. Empty when the definition is consistent."""
    from hangar import harness_lock as hl

    cat = catalog(root)
    spec = cat.get(ENV_NAME)
    raw = cat.raw(ENV_NAME)
    out: list[str] = []
    env = spec.env
    missing = [p for p in PINS if not env.get(p)]
    if missing:
        return [f"env {ENV_NAME}: pin(s) missing: {', '.join(missing)}"]
    harness = env["AGENT_ENV_HARNESS"]
    if raw.get("extends") != harness:
        out.append(f"env {ENV_NAME}: extends {raw.get('extends')!r}, but AGENT_ENV_HARNESS is {harness!r}")
    lock_dir = root / "harnesses" / harness
    if not (lock_dir / hl.LOCK_FILE).is_file():
        return [*out, f"env {ENV_NAME}: AGENT_ENV_HARNESS {harness!r} has no harnesses/{harness}/{hl.LOCK_FILE}"]
    lock = hl.load(lock_dir)
    digest = hl.harness_digest(lock)
    if env["AGENT_ENV_HARNESS_DIGEST"] != digest:
        out.append(f"env {ENV_NAME}: AGENT_ENV_HARNESS_DIGEST is {env['AGENT_ENV_HARNESS_DIGEST']}, but "
                   f"{harness} provides r{lock.get('revision')} {digest}")
    channels = yaml.safe_load((root / "channels.yaml").read_text()) or {}
    named = [ch for ch, d in (channels.get(harness) or {}).items() if d == env["AGENT_ENV_HARNESS_DIGEST"]]
    if not named:
        out.append(f"env {ENV_NAME}: AGENT_ENV_HARNESS_DIGEST is no channel of {harness} in channels.yaml")
    if spec.model != (lock.get("model") or {}).get("id"):
        out.append(f"env {ENV_NAME}: model {spec.model!r} is not the harness lock's {lock.get('model')}")
    ref = env["AI_DLC_REF"]
    if not re.fullmatch(r"[0-9a-f]{40}", ref):
        out.append(f"env {ENV_NAME}: AI_DLC_REF must be a full commit SHA, not {ref!r}")
    elif ref not in (spec.dependencies.script or ""):
        out.append(f"env {ENV_NAME}: dependencies.script does not install ai-dlc at AI_DLC_REF {ref}")
    if not str(env["KNOWLEDGE_FORMAT_VERSION"]).isdigit():
        out.append(f"env {ENV_NAME}: KNOWLEDGE_FORMAT_VERSION must be an integer")
    names = contract_names(root / "environments" / "agent.env.example")
    if set(spec.secrets) - set(names):
        out.append(f"agent.env.example lacks the spec's secrets: {', '.join(sorted(set(spec.secrets) - set(names)))}")
    if set(INPUTS) - set(names):
        out.append(f"agent.env.example lacks the inputs: {', '.join(sorted(set(INPUTS) - set(names)))}")
    if clash := sorted(set(names) & set(spec.env)):
        out.append(f"agent.env.example names values the spec fixes: {', '.join(clash)}")
    e = spec.egress
    if e is None or e.mode != "allowlist":
        out.append(f"env {ENV_NAME}: egress.mode must be allowlist")
    return out


def egress_rules(spec: Any) -> list[list]:
    """The allowlist a hangar sandbox of `spec` gets (no package mirror, nothing approved): [host, wildcard, port]."""
    from hangar import egress

    settings = SimpleNamespace(egress_default="allowlist", package_mirror=False, gateway_url=None)
    policy = egress.resolve(settings, spec, harness=spec.harnesses[0])
    return [[r.host, r.wildcard, r.port] for r in policy.rules]


# ------------------------------------------------------------------------------------------------ docker
def docker(*args: str, input: bytes | None = None, check: bool = True, capture: bool = True):
    r = subprocess.run(["docker", *args], input=input, capture_output=capture)
    if check and r.returncode != 0:
        err = (r.stderr or b"").decode(errors="replace").strip()
        raise SystemExit(f"docker {' '.join(args[:2])} failed: {err[-2000:]}")
    return r


def build(spec: Any, harness: str, extra_ca: Path | None) -> str:
    from hangar.envspec import render

    bake = [spec.harnesses[0]] if harness == "bake" else None
    ctx = render(spec, bake=bake, extra_ca=extra_ca.read_bytes() if extra_ca else None)
    tag = f"team-harness-agent:{ctx.digest}{'' if bake else '-nopack'}"
    if docker("image", "inspect", tag, check=False).returncode != 0:
        print(f"building {tag} (hangar's render of environment {spec.name}) ...", file=sys.stderr)
        r = subprocess.run(["docker", "build", "-t", tag, "-"], input=ctx.tar(), capture_output=True)
        if r.returncode != 0:
            raise SystemExit(f"docker build failed:\n{r.stdout.decode(errors='replace')[-3000:]}"
                             f"{r.stderr.decode(errors='replace')[-3000:]}")
    return tag


def names(instance: str) -> SimpleNamespace:
    return SimpleNamespace(agent=f"agent-env-{instance}", proxy=f"agent-env-{instance}-egress",
                           net=f"agent-env-{instance}-net")


def start(spec: Any, image: str, instance: str, environ: dict[str, str]) -> SimpleNamespace:
    """The sidecar on the default bridge and an internal network, then the agent on the internal network only."""
    n = names(instance)
    labels = ["--label", f"{LABEL}={instance}"]
    docker("network", "create", "--internal", *labels, n.net)
    docker("run", "-d", "--name", n.proxy, *labels, "-e", f"EGRESS_RULES={json.dumps(egress_rules(spec))}",
           "-e", f"EGRESS_PORT={PROXY_PORT}", PROXY_IMAGE, "python", "-c",
           (ROOT / "scripts" / "egress_proxy.py").read_text())
    docker("network", "connect", "--alias", "egress", n.net, n.proxy)
    proxy = f"http://egress:{PROXY_PORT}"
    passed = [k for k in contract_names() if environ.get(k)]
    with tempfile.NamedTemporaryFile("w", suffix=".env", delete=False) as fh:  # values never reach argv
        for k in passed:
            fh.write(f"{k}={environ[k]}\n")
        env_file = fh.name
    try:
        docker("run", "-d", "--name", n.agent, *labels, "--network", n.net, "--env-file", env_file,
               *(x for k in ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy") for x in ("-e", f"{k}={proxy}")),
               "-e", "NO_PROXY=localhost,127.0.0.1", "-e", "no_proxy=localhost,127.0.0.1", image)
    finally:
        os.unlink(env_file)
    print(f"started {n.agent}: {image}; variables passed by name: {', '.join(passed) or 'none'}", file=sys.stderr)
    return n


def sh(container: str, script: str, check: bool = False) -> subprocess.CompletedProcess:
    return docker("exec", container, "bash", "-lc", script, check=check)


def clone_inputs(container: str) -> list[str]:
    """Clone CODE_REPO and KNOWLEDGE_REPO inside the container (through the proxy), and write ai-dlc's machine file."""
    script = f"""set -e
[ -n "$GH_TOKEN" ] && gh auth setup-git >/dev/null 2>&1 || true
for pair in code:CODE_REPO knowledge:KNOWLEDGE_REPO; do
  dir=${{pair%%:*}}; var=${{pair#*:}}; url=${{!var}}
  if [ -z "$url" ]; then echo "input $var is not set"; continue; fi
  [ -d "/workspace/$dir/.git" ] || git clone --quiet --depth 1 "$url" "/workspace/$dir"
done
mkdir -p /workspace/.agent-env
cat > /workspace/.agent-env/machine.toml <<'EOF'
{MACHINE_TOML}EOF
"""
    r = sh(container, script)
    out = (r.stdout + r.stderr).decode(errors="replace").strip()
    if r.returncode != 0:
        raise SystemExit(f"cloning the inputs failed:\n{out}")
    return [line for line in out.splitlines() if line]


REPORT = r"""echo "agent-env: $AGENT_ENV"
echo "harness: $AGENT_ENV_HARNESS $AGENT_ENV_HARNESS_DIGEST"
echo "ai-dlc: $(ai-dlc --version 2>&1) at $AI_DLC_REF"
echo "knowledge format: $KNOWLEDGE_FORMAT_VERSION"
echo "agent: $(claude --version 2>/dev/null || echo 'not baked')"
echo "python: $(python --version 2>&1); uv: $(uv --version 2>&1); gh: $(gh --version 2>&1 | head -1)"
echo "code: $(git -C /workspace/code rev-parse HEAD 2>/dev/null || echo none)"
echo "knowledge: $(git -C /workspace/knowledge rev-parse HEAD 2>/dev/null || echo none)"
echo "--- ai-dlc doctor"
root=/workspace/code; [ -f "$root/ai-dlc.toml" ] || root=/workspace
ai-dlc doctor --root "$root" --machine /workspace/.agent-env/machine.toml
"""


def report(container: str, model: str) -> tuple[int, str]:
    r = sh(container, REPORT)
    text = f"model: {model}\n" + (r.stdout + r.stderr).decode(errors="replace")
    return r.returncode, text


def down(instance: str | None = None) -> None:
    flt = f"label={LABEL}" + (f"={instance}" if instance else "")
    ids = docker("ps", "-aq", "--filter", flt).stdout.decode().split()
    if ids:
        docker("rm", "-f", *ids)
    nets = docker("network", "ls", "-q", "--filter", flt).stdout.decode().split()
    if nets:
        docker("network", "rm", *nets)


def up(args: argparse.Namespace, instance: str) -> tuple[SimpleNamespace, Any]:
    problems = pin_problems()
    if problems:
        raise SystemExit("the agent environment's pins disagree:\n  " + "\n  ".join(problems))
    spec = catalog().get(ENV_NAME)
    image = build(spec, args.harness, args.extra_ca)
    n = start(spec, image, instance, dict(os.environ))
    for line in clone_inputs(n.agent):
        print(line, file=sys.stderr)
    return n, spec


# ------------------------------------------------------------------------------------------------ the checks
def check(args: argparse.Namespace) -> int:
    """The acceptance checks: two fresh instances report the same; nothing is mounted; egress is refused off-list."""
    failures: list[str] = []
    texts: list[str] = []
    try:
        for i in (1, 2):
            n, spec = up(args, f"check{i}-{uuid.uuid4().hex[:6]}")
            code, text = report(n.agent, spec.model)
            texts.append(text)
            print(f"instance {i}: doctor exit {code}", file=sys.stderr)
            if code != 0:
                failures.append(f"instance {i}: ai-dlc doctor failed (exit {code}); its report is printed below")
            mounts = json.loads(docker("inspect", "-f", "{{json .Mounts}}", n.agent).stdout or b"[]")
            if mounts:
                failures.append(f"instance {i} has mounts: {mounts}")
            if i == 1:
                before = len(failures)
                ok = sh(n.agent, "curl -fsS -o /dev/null -I --max-time 20 https://github.com/")
                if ok.returncode != 0:
                    failures.append(f"an allowed host failed: {ok.stderr.decode(errors='replace').strip()}")
                for url in ("https://example.com/", "http://example.com/"):
                    bad = sh(n.agent, f"curl -fsS -o /dev/null --max-time 20 {url}")
                    if bad.returncode == 0:
                        failures.append(f"{url} is off the allowlist and was reached")
                direct = sh(n.agent, "env -u HTTPS_PROXY -u https_proxy curl -fsS -o /dev/null --max-time 10 "
                                     "https://github.com/")
                if direct.returncode == 0:
                    failures.append("a request that skipped the proxy got out")
                print("egress: allowed host reached; off-list and proxy-skipping requests refused"
                      if len(failures) == before else "egress: FAILED", file=sys.stderr)
        if texts[0] != texts[1]:
            import difflib

            diff = "".join(difflib.unified_diff(texts[0].splitlines(True), texts[1].splitlines(True), "1", "2"))
            failures.append(f"the two instances differ:\n{diff}")
        else:
            print("two fresh instances: identical pins and doctor output", file=sys.stderr)
        print(texts[0])
    finally:
        if not args.keep:
            down()
    for f in failures:
        print(f"FAIL: {f}", file=sys.stderr)
    return 1 if failures else 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["up", "report", "exec", "check", "down", "policy"], nargs="?", default="up")
    p.add_argument("--instance", help="name of the local instance (default: local; down: every instance)")
    p.add_argument("--harness", choices=["bake", "none"], default="bake",
                   help="bake the agent CLI into the image (default), or leave it out as a hangar image without its "
                        "pack mount is")
    p.add_argument("--extra-ca", type=Path, help="a CA certificate to trust in the image (TLS-intercepting networks)")
    p.add_argument("--keep", action="store_true", help="check: leave the instances running")
    argv = list(sys.argv[1:] if argv is None else argv)
    rest = argv[argv.index("--") + 1:] if "--" in argv else []
    args = p.parse_args(argv[:argv.index("--")] if "--" in argv else argv)
    if args.command == "policy":
        problems = pin_problems()
        for rule in egress_rules(catalog().get(ENV_NAME)):
            print(("*." if rule[1] else "") + rule[0] + (f":{rule[2]}" if rule[2] else ""))
        for x in problems:
            print(f"error: {x}", file=sys.stderr)
        return 1 if problems else 0
    if args.command == "check":
        return check(args)
    if args.command == "down":
        down(args.instance)
        return 0
    args.instance = args.instance or "local"
    n = names(args.instance)
    if args.command == "up":
        down(args.instance)
        n, spec = up(args, args.instance)
        code, text = report(n.agent, spec.model)
        print(text, end="")
        print(f"\n{n.agent} is running: `python scripts/agent_env.py exec -- <command>`; stop it with "
              "`make agent-env-down`", file=sys.stderr)
        return code
    if args.command == "report":
        code, text = report(n.agent, catalog().get(ENV_NAME).model)
        print(text, end="")
        return code
    tty = "-it" if sys.stdin.isatty() else "-i"
    return subprocess.call(["docker", "exec", tty, n.agent, *(rest or ["bash", "-l"])])


if __name__ == "__main__":
    sys.exit(main())
