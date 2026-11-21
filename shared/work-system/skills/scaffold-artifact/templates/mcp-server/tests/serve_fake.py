"""The server on the fake backend over stdio, for the artifact check's golden calls in CI (no service, no
credentials): `python tests/serve_fake.py`."""

from __future__ import annotations

from fakes import FakeBackend

from @@package@@.server import build_server

if __name__ == "__main__":
    build_server(FakeBackend()).run("stdio")
