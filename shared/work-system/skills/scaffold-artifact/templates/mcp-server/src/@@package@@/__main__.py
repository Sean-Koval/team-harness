"""Run the server over stdio: `python -m @@package@@` (or the `@@project@@` command)."""

from __future__ import annotations

from .backend import ServiceBackend
from .server import build_server


def main() -> None:
    build_server(ServiceBackend()).run("stdio")


if __name__ == "__main__":
    main()
