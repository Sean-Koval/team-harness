"""The server's contract: every tool is listed with a description and a valid input schema, and every golden call
in evals/golden/ returns what it says, on the fake backend."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from fakes import FakeBackend
from jsonschema import Draft202012Validator

from @@package@@.server import build_server

GOLDEN = sorted((Path(__file__).resolve().parents[1] / "evals" / "golden").glob("*.json"))


def tools() -> list[Any]:
    return asyncio.run(build_server(FakeBackend()).list_tools())


def test_the_server_lists_tools():
    assert tools(), "the server lists no tools"


def test_every_tool_has_a_description_and_a_valid_input_schema():
    for tool in tools():
        assert (tool.description or "").strip(), f"tool {tool.name} has no description"
        schema = tool.input_schema
        Draft202012Validator.check_schema(schema)
        assert schema.get("type") == "object", f"tool {tool.name}: input schema is not an object"
        assert set(schema.get("required", [])) <= set(schema.get("properties", {})), tool.name


def test_every_tool_has_a_golden_case():
    covered = {json.loads(p.read_text(encoding="utf-8"))["tool"] for p in GOLDEN}
    assert {t.name for t in tools()} <= covered, "add a golden case under evals/golden/ for each tool"


@pytest.mark.parametrize("case", GOLDEN, ids=lambda p: p.stem)
def test_golden_call(case: Path):
    spec = json.loads(case.read_text(encoding="utf-8"))
    schema = next(t.input_schema for t in tools() if t.name == spec["tool"])
    Draft202012Validator(schema).validate(spec["arguments"])
    result = asyncio.run(build_server(FakeBackend()).call_tool(spec["tool"], spec["arguments"]))
    assert getattr(result, "is_error", False) is spec.get("is_error", False)
    if "structured_content" in spec:
        assert getattr(result, "structured_content", None) == spec["structured_content"]
