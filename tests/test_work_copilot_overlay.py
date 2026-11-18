"""scripts/work_copilot_overlay.py: the org overlay feeds Work Copilot's config (KAN-381)."""

import copy
import json
import os
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import install_local as il  # noqa: E402
import work_copilot_overlay as wco  # noqa: E402

EXAMPLE = yaml.safe_load((ROOT / "orgs/example-co/org.yaml").read_text(encoding="utf-8"))
PROFILE = "shared/work-system/profiles/work-default.yaml"

# Work Copilot's formats, field -> (accepted, refused). work-copilot's tests/test_overlay.py holds the same table:
# keep the two identical, as the two format definitions are.
FORMAT_CASES = {
    "work_site": (["example-co.atlassian.net", "wiki.example.invalid", "a.b", "COMPANY-SITE.atlassian.net"],
                  ["example", "-x.example", "example.com/wiki", "exa mple.com", "https://example.com", ""]),
    "kb_space": (["ENG", "~jdoe", "~5b10ac8d82e05b22cc7d4ef5", "team_docs-2", "x" * 64],
                 ["~", "~~x", "a~b", "-ENG", "E NG", "x" * 65, ""]),
    "jira_project": (["ENG", "A", "FIC_2", "WORKPROJ"], ["eng", "1ENG", "E-NG", "A" * 21, ""]),
    "room": (["#eng-review", "the team's review room", "x" * 200],
             ["", "a\nb", "a b", "a b", "a\x85b", "a\x9fb", "a\x7fb", "x" * 201]),
}


def fictional() -> dict:
    """A filled-in fictional company: what a private fork's org.yaml looks like."""
    org = copy.deepcopy(EXAMPLE)
    org.update(name="fictional-co", placeholder=False)
    org["params"] = {"tracker": "the FIC project", "kb_site": "fictional.example.invalid", "kb_space": "FICDOCS"}
    org["ticket_types"][0]["project"] = "FIC"
    org["review_request"]["room"] = "Fictional review room"
    return org


# What this script renders for the fictional org in a fork (`fork(tmp_path, fictional())`). work-copilot's
# tests/fixtures/overlay/fictional-co.json holds this same JSON, and the example's as example-co.json, as goldens
# that its `validate` must accept.
FICTIONAL_JSON = {
    "schema": "work-copilot.overlay/v1", "name": "fictional-co", "placeholder": False,
    "source": "orgs/fictional-co/org.yaml", "work_site": "fictional.example.invalid", "kb_space": "FICDOCS",
    "jira_project": "FIC", "room": "Fictional review room"}


def fork(tmp: Path, org: dict, harness: str = "work-default") -> Path:
    """A repository tree with targets.yaml, the profiles and `org` as orgs/<name>/, named by `harness`."""
    root = tmp / "fork"
    shutil.copytree(ROOT / "shared/work-system/profiles", root / "shared/work-system/profiles")
    t = yaml.safe_load((ROOT / "shared/work-system/targets.yaml").read_text(encoding="utf-8"))
    t["harnesses"][harness]["org"] = f"orgs/{org['name']}"
    (root / "shared/work-system/targets.yaml").write_text(yaml.safe_dump(t), encoding="utf-8")
    d = root / "orgs" / org["name"]
    shutil.copytree(ROOT / "orgs/example-co/skills", d / "skills")
    (d / "org.yaml").write_text(yaml.safe_dump(org, sort_keys=False), encoding="utf-8")
    return root


def text(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False) + "\n"


@pytest.mark.parametrize("field", sorted(FORMAT_CASES))
def test_the_formats_are_work_copilots(field):
    accepted, refused = FORMAT_CASES[field]
    assert all(wco.FORMATS[field].fullmatch(v) for v in accepted)
    assert not any(wco.FORMATS[field].fullmatch(v) for v in refused)


def test_a_filled_in_org_renders_work_copilot_config(tmp_path):
    assert wco.overlay(fictional(), "orgs/fictional-co/org.yaml") == FICTIONAL_JSON
    assert wco.render(fork(tmp_path, fictional()), harness="work-default") == FICTIONAL_JSON
    assert list(wco.render(fork(tmp_path / "2", fictional()), harness="work-default")) == list(FICTIONAL_JSON)


def test_the_example_renders_as_a_placeholder():
    out = wco.render(ROOT, org="orgs/example-co")
    assert out == wco.render(ROOT, harness="work-default")
    assert out["placeholder"] is True and out["name"] == "example-co" and out["jira_project"] == "WORKPROJ"
    assert out["source"] == "orgs/example-co/org.yaml"


def test_values_are_normalised_to_work_copilots_form(tmp_path):
    org = fictional()
    org["params"].update(kb_site="  https://fictional.example.invalid/ ", kb_space=" ~ficuser ")
    org["review_request"]["room"] = "  #fic-review\n"
    org["ticket_types"][0]["project"] = " FIC "
    out = wco.render(fork(tmp_path, org), harness="work-default")
    assert (out["work_site"], out["kb_space"], out["room"], out["jira_project"]) == (
        "fictional.example.invalid", "~ficuser", "#fic-review", "FIC")


@pytest.mark.parametrize("change, where, field", [
    (lambda o: o["params"].update(kb_site="fictional.example.invalid/wiki"), "orgs/fictional-co/org.yaml",
     "params.kb_site"),
    (lambda o: o["params"].update(kb_space="FIC DOCS"), "orgs/fictional-co/org.yaml", "params.kb_space"),
    (lambda o: o["ticket_types"][0].update(project="fic"), "orgs/fictional-co/org.yaml", "ticket_types[0].project"),
    (lambda o: o["review_request"].update(room="review room"), "orgs/fictional-co/org.yaml",
     "review_request.room"),
])
def test_a_value_work_copilot_would_refuse_names_the_file_and_field(tmp_path, change, where, field):
    org = fictional()
    change(org)
    with pytest.raises(ValueError) as e:
        wco.render(fork(tmp_path, org), harness="work-default")
    assert str(e.value).startswith(f"{where}: {field} ") and "expected" in str(e.value)


def test_an_org_without_kb_values_gets_the_profiles(tmp_path):
    org = fictional()
    org["params"] = {"tracker": "the FIC project"}
    profile = yaml.safe_load((ROOT / PROFILE).read_text(encoding="utf-8"))["params"]
    out = wco.render(fork(tmp_path, org), harness="work-default")
    assert (out["work_site"], out["kb_space"]) == (profile["kb_site"], profile["kb_space"])
    # and a bad profile value is reported as the profile's
    (tmp_path / "fork" / PROFILE).write_text(
        (ROOT / PROFILE).read_text(encoding="utf-8").replace('kb_space: "COMPANY-SPACE"', 'kb_space: "NO SPACE"'),
        encoding="utf-8")
    with pytest.raises(ValueError, match=f"^{PROFILE}: params.kb_space 'NO SPACE'"):
        wco.render(tmp_path / "fork", harness="work-default")


def test_an_org_with_no_work_ticket_type_leaves_out_the_jira_project(tmp_path):
    org = fictional()
    org["ticket_types"] = [t for t in org["ticket_types"] if t.get("role") != "work"]
    org["gates"] = [g for g in org["gates"] if g.get("approved_on") != "work"]  # KAN-373: such a gate needs a work type
    out = wco.render(fork(tmp_path, org), harness="work-default")
    assert "jira_project" not in out and out["work_site"] == "fictional.example.invalid"


def test_the_overlay_carries_nothing_but_the_org_values():
    out = wco.overlay(fictional(), "x")
    assert set(out) <= {"schema", "name", "placeholder", "source", "work_site", "kb_space", "jira_project", "room"}
    assert not any(word in json.dumps(out).lower() for word in ("token", "secret", "password", "bearer"))


def test_an_invalid_org_is_refused():
    bad = fictional()
    bad["params"]["merge_rule"] = "anything"
    with pytest.raises(ValueError, match="merge_rule"):
        wco.overlay(bad, "orgs/fictional-co/org.yaml")


def test_only_a_directory_under_orgs_is_read(tmp_path):
    with pytest.raises(ValueError, match="under orgs/"):
        wco.render(ROOT, org="shared")
    with pytest.raises(ValueError, match="names no org"):
        wco.render(ROOT, harness="suite-default")
    with pytest.raises(ValueError, match="takes no org overlay"):
        wco.render(ROOT, harness="suite-default", org="orgs/example-co")


def test_source_is_relative_to_the_repository_root_whatever_the_separators():
    for given in ("orgs/example-co/", "orgs\\example-co\\", str(ROOT / "orgs/example-co")):
        assert wco.render(ROOT, org=given)["source"] == "orgs/example-co/org.yaml"


def test_the_cli_writes_the_file(tmp_path, capsys, monkeypatch):
    out = tmp_path / "work-copilot-overlay.json"
    assert wco.main(["--org", "orgs/example-co", "--out", str(out)]) == 0
    assert json.loads(out.read_text(encoding="utf-8"))["name"] == "example-co"
    printed = capsys.readouterr().out
    assert wco.PLACEHOLDER_NOTE in printed
    assert f"<your Work Copilot launcher> --data-dir <your data dir> overlay apply {out}" in printed
    assert f"./run.sh --data-dir <your data dir> overlay apply {out}" in printed
    assert wco.main(["--org", "orgs/missing"]) == 2
    monkeypatch.setattr(wco, "WINDOWS", True)
    assert wco.main(["--harness", "work-default", "--out", str(out)]) == 0
    assert f".\\run.ps1 --data-dir <your data dir> overlay apply '{out}'" in capsys.readouterr().out


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                           "-c", "commit.gpgsign=false", *args], capture_output=True, text=True, check=True).stdout


def history(tmp_path: Path) -> tuple[Path, str]:
    """A fork in git whose org's space was OLD at the returned commit and is NEW now."""
    org = fictional()
    org["params"]["kb_space"] = "OLD"
    root = fork(tmp_path, org)
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-qm", "old")
    old = _git(root, "rev-parse", "HEAD").strip()
    org["params"]["kb_space"] = "NEW"
    (root / "orgs/fictional-co/org.yaml").write_text(yaml.safe_dump(org, sort_keys=False), encoding="utf-8")
    _git(root, "commit", "-qam", "new")
    return root, old


def test_at_reads_the_org_and_targets_at_that_commit(tmp_path, monkeypatch, capsys):
    root, old = history(tmp_path)
    with wco.tree(root, old) as at:
        assert wco.render(at, harness="work-default")["kb_space"] == "OLD"
    assert wco.render(root, harness="work-default")["kb_space"] == "NEW"
    monkeypatch.setattr(wco, "ROOT", root)
    assert wco.main(["--harness", "work-default", "--at", old[:12]]) == 0
    assert json.loads(capsys.readouterr().out)["kb_space"] == "OLD"
    assert wco.main(["--harness", "work-default", "--at", "no-such-commit"]) == 2
    assert "no such commit" in capsys.readouterr().err
    assert wco.main(["--harness", "work-default", "--at=--output=x"]) == 2
    assert "is not a commit" in capsys.readouterr().err


def test_install_local_prints_the_commands_only_for_a_harness_with_an_org(tmp_path):
    steps = il.work_copilot_commands(ROOT, "work-default", out=tmp_path / "o.json")
    assert len(steps.commands) == 2 and not steps.problem
    assert steps.commands[0].startswith("python3 ") and "work_copilot_overlay.py" in steps.commands[0]
    assert "--harness work-default --out" in steps.commands[0] and "--at" not in steps.commands[0]
    assert steps.commands[1] == (f"<your Work Copilot launcher> --data-dir <your data dir> overlay apply "
                                 f"{tmp_path / 'o.json'}")
    assert steps.example.endswith(f"./run.sh --data-dir <your data dir> overlay apply {tmp_path / 'o.json'}")
    assert steps.note == "(placeholder org: values are examples)"
    assert il.work_copilot_commands(ROOT, "suite-default") is None


def test_install_local_on_windows_quotes_every_path_and_uses_py(tmp_path, monkeypatch):
    monkeypatch.setattr(il, "WINDOWS", True)
    out = tmp_path / "o.json"
    steps = il.work_copilot_commands(ROOT, "work-default", out=out)
    script = ROOT / "scripts" / "work_copilot_overlay.py"
    assert steps.commands[0] == f"py -3 '{script}' --harness work-default --out '{out}'"
    assert steps.commands[1].endswith(f"overlay apply '{out}'")
    assert f".\\run.ps1 --data-dir <your data dir> overlay apply '{out}'" in steps.example


def test_a_windows_path_with_a_dollar_or_a_quote_stays_one_powershell_word():
    assert wco.quote("C:\\Users\\o'neil\\$work\\o.json", windows=True) == "'C:\\Users\\o''neil\\$work\\o.json'"


def test_install_local_pins_the_overlay_to_the_revision_it_installs(tmp_path):
    root, old = history(tmp_path)
    steps = il.work_copilot_commands(root, "work-default", old, out=tmp_path / "o.json")
    assert f"--harness work-default --at {old} --out" in steps.commands[0]
    assert steps.note == "" and not steps.problem  # the fictional org is no placeholder


def test_install_local_survives_a_malformed_targets_yaml_or_a_missing_script(tmp_path, monkeypatch):
    root = fork(tmp_path, fictional())
    (root / "shared/work-system/targets.yaml").write_text("harnesses: [1, {a: b}]\n", encoding="utf-8")
    steps = il.work_copilot_commands(root, "work-default")
    assert steps is None or (steps.commands == [] and steps.problem)
    (root / "shared/work-system/targets.yaml").write_text("harnesses:\n  work-default: [x]\n", encoding="utf-8")
    assert il.work_copilot_commands(root, "work-default") is None
    (root / "shared/work-system/targets.yaml").write_text("- a list\n", encoding="utf-8")
    steps = il.work_copilot_commands(root, "work-default")
    assert steps.commands == [] and "targets.yaml" in steps.problem
    monkeypatch.setitem(sys.modules, "work_copilot_overlay", None)  # importing it raises ImportError
    steps = il.work_copilot_commands(ROOT, "work-default")
    assert steps.commands == [] and "cannot load" in steps.problem


def test_install_local_reports_an_org_that_does_not_render(tmp_path):
    org = fictional()
    org["ticket_types"][0]["project"] = "fic"
    steps = il.work_copilot_commands(fork(tmp_path, org), "work-default")
    assert len(steps.commands) == 2 and "ticket_types[0].project" in steps.problem


# Work Copilot's own copies of these two files (tests/fixtures/overlay/ there) are what its `overlay apply` checks
# against; keep the two sets byte for byte the same.
GOLDEN = Path(__file__).resolve().parent / "fixtures" / "work-copilot-overlay"


@pytest.mark.parametrize("name", ["example-co", "fictional-co"])
def test_the_rendered_overlay_matches_work_copilots_sample_files(tmp_path, name):
    out = (wco.render(ROOT, harness="work-default") if name == "example-co"
           else wco.render(fork(tmp_path, fictional()), harness="work-default"))
    assert text(out) == (GOLDEN / f"{name}.json").read_text(encoding="utf-8")


def _work_copilot_overlay():
    """Work Copilot's overlay module from a checkout (WORK_COPILOT_CHECKOUT), else skip: CI has no Work Copilot."""
    checkout = os.environ.get("WORK_COPILOT_CHECKOUT")
    if not checkout:
        pytest.skip("set WORK_COPILOT_CHECKOUT to a Work Copilot checkout to check against its overlay validator")
    import importlib.util
    spec = importlib.util.spec_from_file_location("wc_overlay", Path(checkout) / "work_copilot" / "overlay.py")
    if spec is None or not Path(spec.origin).is_file():
        pytest.fail(f"WORK_COPILOT_CHECKOUT has no work_copilot/overlay.py: {checkout}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_work_copilots_strict_checks_accept_what_this_renders(tmp_path):
    wc = _work_copilot_overlay()
    for org in (None, fictional()):
        out = wco.render(ROOT if org is None else fork(tmp_path / "f", org), harness="work-default")
        assert wc.validate(out) == out
        f = tmp_path / "o.json"
        f.write_text(text(out), encoding="utf-8")
        assert wc.read(f) == out
    for name in ("example-co", "fictional-co"):
        golden = GOLDEN / name
        assert wc.read(golden.with_suffix(".json")) == json.loads(golden.with_suffix(".json").read_text("utf-8"))


def test_the_two_format_definitions_are_the_same():
    wc = _work_copilot_overlay()
    assert set(wc._FIELDS) == set(wco.FORMATS)
    # The two are written with different escapes, so compare what they accept: the shared cases, then every
    # character from U+0000 to U+30FF on its own and inside a valid value.
    probes = [v for field in FORMAT_CASES for case in FORMAT_CASES[field] for v in case]
    probes += [c for i in range(0x3100) for c in (chr(i), f"a{chr(i)}.b", f"A{chr(i)}")]
    for field, pattern in wco.FORMATS.items():
        differ = [v for v in probes if bool(pattern.fullmatch(v)) != bool(wc._FIELDS[field].fullmatch(v))]
        assert not differ, f"{field}: Work Copilot and this script disagree on {differ[:5]!r}"


def test_the_default_overlay_file_is_in_the_users_own_config_folder(tmp_path):
    home = tmp_path / "home"
    assert wco.default_out(home, {}, windows=False) == home / ".config/team-harness/work-copilot-overlay.json"
    assert wco.default_out(home, {"XDG_CONFIG_HOME": str(tmp_path / "x")}, windows=False) == \
        tmp_path / "x/team-harness/work-copilot-overlay.json"
    assert wco.default_out(home, {"APPDATA": str(tmp_path / "ad")}, windows=True) == \
        tmp_path / "ad/team-harness/work-copilot-overlay.json"
    assert wco.default_out(home, {}, windows=True) == home / "AppData/Roaming/team-harness/work-copilot-overlay.json"


@pytest.mark.skipif(sys.platform == "win32", reason="runs the POSIX line; the Windows line is checked as text above")
def test_the_printed_commands_never_write_into_the_current_folder_unless_asked(tmp_path, monkeypatch):
    """install_local may run inside a company repository: by default the overlay goes to the user's config folder."""
    work, cfg = tmp_path / "company-repo", tmp_path / "cfg"
    work.mkdir()
    monkeypatch.chdir(work)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    steps = il.work_copilot_commands(ROOT, "work-default")
    want = cfg / "team-harness" / "work-copilot-overlay.json"
    assert steps.commands[1].endswith(f"overlay apply {want}")
    words = shlex.split(steps.commands[0])
    assert words[0] == "python3"
    r = subprocess.run([sys.executable, *words[1:]], cwd=work, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert list(work.iterdir()) == []  # nothing in the current folder
    assert json.loads(want.read_text(encoding="utf-8"))["name"] == "example-co"
    assert want.parent.stat().st_mode & 0o777 == 0o700  # a folder the script made is private

    # the script alone, with no --out, prints and writes nothing
    r = subprocess.run([sys.executable, str(ROOT / "scripts/work_copilot_overlay.py"), "--harness", "work-default"],
                       cwd=work, capture_output=True, text=True)
    assert r.returncode == 0 and json.loads(r.stdout)["name"] == "example-co" and list(work.iterdir()) == []


def test_overlay_out_chooses_another_file(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    mine = tmp_path / "elsewhere" / "overlay.json"
    rc = il.main([str(ROOT / "harnesses/work-default"), "--scope", "user", "--home", str(tmp_path / "home"),
                  "--channel", "checkout", "--allow-dirty", "--overlay-out", str(mine)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert f"--out {mine}" in out and f"overlay apply {mine}" in out and str(tmp_path / "cfg") not in out
    assert not mine.exists()  # install_local only prints the command
