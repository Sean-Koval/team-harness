"""A fake Backend with fixed data, so the contract test and golden calls need no network or credentials."""

from __future__ import annotations

from @@package@@.backend import Item

ITEMS: list[Item] = [
    {"id": "1", "title": "First example item"},
    {"id": "2", "title": "Second example item"},
    {"id": "3", "title": "Something else"},
]


class FakeBackend:
    def search(self, query: str, limit: int) -> list[Item]:
        return [i for i in ITEMS if query.lower() in i["title"].lower()][:limit]
