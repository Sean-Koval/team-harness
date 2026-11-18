"""The service the tools call. Tests use a fake (tests/fakes.py); the server never talks to it directly."""

from __future__ import annotations

from typing import Protocol, TypedDict


class Item(TypedDict):
    id: str
    title: str


class Backend(Protocol):
    def search(self, query: str, limit: int) -> list[Item]: ...


class ServiceBackend:
    """The real backend. Wire it to the service the ticket names; read credentials from the environment, never
    from a file in the repository."""

    def search(self, query: str, limit: int) -> list[Item]:
        raise NotImplementedError("connect ServiceBackend.search to the service")
