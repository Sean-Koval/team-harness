#!/usr/bin/env python3
"""The local stand-in for hangar's egress proxy: an HTTP CONNECT proxy that lets through only the allowlist.

scripts/agent_env.py runs it in a sidecar container, the only way out of the agent's internal Docker network. The
allowlist is not decided here: agent_env.py asks hangar's own `egress.resolve` for the policy a hangar sandbox of the
environment would get and passes its rules in `EGRESS_RULES` (JSON `[[host, wildcard, port], ...]`). `allowed` is
hangar's `Rule.matches`; tests/test_agent_env.py holds the two to the same answers. Standard library only, so the
sidecar is a stock Python image.

What it does, a subset of hangar's (docs/security/egress.md in hangar): CONNECT only (a plain-HTTP request gets 405,
so a tool that skips the proxy or speaks plain HTTP fails closed); the host and port must match a rule; the name must
resolve to public addresses only, and the tunnel goes to the address it checked. It doesn't inspect the TLS hello.
Each decision is one line on stderr.
"""

from __future__ import annotations

import ipaddress
import json
import os
import select
import socket
import socketserver
import sys

DEFAULT_PORTS = (443, 80)  # hangar egress.DEFAULT_PORTS: a rule without a port


def allowed(rules: list[list], host: str, port: int) -> bool:
    """hangar `Rule.matches` over `rules`: exact host, or `*.domain` for any name below it; no port means 443 and 80."""
    host = host.strip().lower().rstrip(".")
    for rule_host, wildcard, rule_port in rules:
        if (port not in DEFAULT_PORTS) if rule_port is None else port != rule_port:
            continue
        if (host.endswith("." + rule_host)) if wildcard else host == rule_host:
            return True
    return False


def public_address(host: str, port: int) -> str | None:
    """The first address `host` resolves to, when every address is public; else None."""
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except OSError:
        return None
    addrs = [i[4][0] for i in infos]
    if not addrs or any(not ipaddress.ip_address(a.split("%")[0]).is_global for a in addrs):
        return None
    return addrs[0]


class Handler(socketserver.StreamRequestHandler):
    rules: list[list] = []

    def _reply(self, status: str) -> None:
        self.wfile.write(f"HTTP/1.1 {status}\r\nContent-Length: 0\r\nConnection: close\r\n\r\n".encode())

    def handle(self) -> None:
        line = self.rfile.readline(8192).decode("latin-1").strip()
        while self.rfile.readline(8192).strip():  # the rest of the request head
            pass
        parts = line.split()
        if len(parts) != 3 or parts[0].upper() != "CONNECT":
            print(f"egress deny: not CONNECT: {line[:120]!r}", file=sys.stderr, flush=True)
            self._reply("405 Method Not Allowed")
            return
        host, _, port_text = parts[1].rpartition(":")
        host = host.strip("[]").lower()
        port = int(port_text) if port_text.isdigit() else 0
        if not allowed(self.rules, host, port):
            print(f"egress deny: {host}:{port} is not on the allowlist", file=sys.stderr, flush=True)
            self._reply("403 Forbidden")
            return
        addr = public_address(host, port)
        if addr is None:
            print(f"egress deny: {host}:{port} does not resolve to public addresses", file=sys.stderr, flush=True)
            self._reply("403 Forbidden")
            return
        try:
            upstream = socket.create_connection((addr, port), timeout=15)
        except OSError as e:
            print(f"egress fail: {host}:{port}: {e}", file=sys.stderr, flush=True)
            self._reply("502 Bad Gateway")
            return
        print(f"egress allow: {host}:{port}", file=sys.stderr, flush=True)
        self._reply("200 Connection Established")
        self._relay(self.connection, upstream)

    @staticmethod
    def _relay(a: socket.socket, b: socket.socket) -> None:
        a.settimeout(None)
        b.settimeout(None)
        try:
            while True:
                ready, _, _ = select.select([a, b], [], [], 900)
                if not ready:
                    return
                for s in ready:
                    data = s.recv(65536)
                    if not data:
                        return
                    (b if s is a else a).sendall(data)
        except OSError:
            return
        finally:
            b.close()


class Server(socketserver.ThreadingTCPServer):
    daemon_threads = True
    allow_reuse_address = True


def main() -> int:
    Handler.rules = [[h, bool(w), p] for h, w, p in json.loads(os.environ.get("EGRESS_RULES") or "[]")]
    port = int(os.environ.get("EGRESS_PORT") or 3128)
    with Server(("0.0.0.0", port), Handler) as server:
        print(f"egress proxy on :{port}, {len(Handler.rules)} rule(s)", file=sys.stderr, flush=True)
        server.serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
