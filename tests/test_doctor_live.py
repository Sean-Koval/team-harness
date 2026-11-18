"""scripts/doctor.py --live's one network call, tools_list: where the credential may go (KAN-540). Plain Python and
loopback sockets only, so these run on Windows too (the rest of test_doctor.py probes hooks through sh)."""

import http.server
import json
import sys
import threading
import urllib.request
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import doctor  # noqa: E402

SECRET = "Bearer s3cret-value-never-printed"
TOKEN = SECRET.split()[1]


class FakeMCP(http.server.BaseHTTPRequestHandler):
    sse = False
    status = 200
    seen: list = []

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        FakeMCP.seen.append((self.headers.get("Authorization"), self.headers.get("Mcp-Session-Id"), body))
        if FakeMCP.status != 200:
            self.send_response(FakeMCP.status)
            self.end_headers()
            return
        if "id" not in body:
            self.send_response(202)
            self.end_headers()
            return
        result = {"tools": [{"name": "a"}, {"name": "b"}]} if body["method"] == "tools/list" else {"capabilities": {}}
        data = json.dumps({"jsonrpc": "2.0", "id": body["id"], "result": result})
        self.send_response(200)
        self.send_header("Mcp-Session-Id", "sess-1")
        if FakeMCP.sse:
            self.send_header("Content-Type", "text/event-stream")
            data = f"event: message\ndata: {data}\n\n"
        else:
            self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(data.encode())

    def log_message(self, *a):
        pass


class Recorder(http.server.BaseHTTPRequestHandler):
    """Records every request, whatever its method (urllib follows a 301/302/303 on a POST as a GET), and answers 200."""
    seen: list = []

    def _record(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n:
            self.rfile.read(n)
        Recorder.seen.append((self.command, self.path, self.headers.get("Authorization")))
        self.send_response(200)
        self.send_header("Content-Length", "0")
        self.end_headers()

    do_GET = do_POST = do_HEAD = do_PUT = do_CONNECT = _record  # noqa: N815

    def log_message(self, *a):
        pass


def serve(handler) -> http.server.HTTPServer:
    srv = http.server.HTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv


@pytest.fixture
def mcp_server():
    FakeMCP.seen, FakeMCP.sse, FakeMCP.status = [], False, 200
    srv = serve(FakeMCP)
    yield f"http://127.0.0.1:{srv.server_port}/mcp"
    srv.shutdown()


@pytest.fixture
def recorder():
    Recorder.seen = []
    srv = serve(Recorder)
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


@pytest.mark.parametrize("sse", [False, True])
def test_tools_list_handshake(mcp_server, sse):
    FakeMCP.sse = sse
    n, err = doctor.tools_list(mcp_server, "Authorization", SECRET)
    assert (n, err) == (2, None)
    assert [b.get("method") for _, _, b in FakeMCP.seen] == ["initialize", "notifications/initialized", "tools/list"]
    assert FakeMCP.seen[-1][:2] == (SECRET, "sess-1")


def test_tools_list_refused(mcp_server):
    FakeMCP.status = 401
    n, err = doctor.tools_list(mcp_server, "Authorization", SECRET)
    assert n == 0 and "401" in err and TOKEN not in err


@pytest.mark.parametrize("endpoint, sends", [
    ("https://mcp.example.invalid/mcp", True), ("HTTPS://mcp.example.invalid/mcp", True),
    ("http://localhost:8080/mcp", True), ("http://127.0.0.1:9/mcp", True), ("http://[::1]:9/mcp", True),
    ("HTTP://LOCALHOST/mcp", True),
    ("http://mcp.example.invalid/mcp", False), ("http://localhost.example.invalid/mcp", False),
    ("http://127.0.0.1.example.invalid/mcp", False), ("ftp://mcp.example.invalid/mcp", False),
    ("mcp.example.invalid/mcp", False), ("", False), ("https:///mcp", False),
    ("http://x@localhost/mcp", False), ("https://user:pw@mcp.example.invalid/mcp", False),
    ("http://evil.example?@localhost/mcp", False),
])
def test_a_credential_goes_only_over_https_or_to_this_machine(endpoint, sends):
    assert doctor.sends_credential_to(endpoint) is sends


def test_tools_list_sends_nothing_to_a_plain_http_endpoint(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a request was made")
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", refuse)
    monkeypatch.setattr(urllib.request, "urlopen", refuse)
    n, err = doctor.tools_list("http://mcp.example.invalid/mcp", "Authorization", SECRET)
    assert n == 0 and "not https" in err and TOKEN not in err


class Redirect(http.server.BaseHTTPRequestHandler):
    code, to, seen = 302, "", []

    def do_POST(self):  # noqa: N802
        self.rfile.read(int(self.headers["Content-Length"]))
        Redirect.seen.append(self.headers.get("Authorization"))
        self.send_response(Redirect.code)
        self.send_header("Location", Redirect.to)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *a):
        pass


@pytest.mark.parametrize("code", [301, 302, 303, 307, 308])
def test_tools_list_follows_no_redirect(recorder, code):
    """A 30x names its status and is not followed: its target, which records any method, sees no request at all."""
    Redirect.code, Redirect.to, Redirect.seen = code, f"{recorder}/elsewhere", []
    srv = serve(Redirect)
    try:
        n, err = doctor.tools_list(f"http://127.0.0.1:{srv.server_port}/mcp", "Authorization", SECRET)
    finally:
        srv.shutdown()
    assert n == 0 and f"HTTP {code}" in err and "redirect" in err and TOKEN not in err
    assert Redirect.seen == [SECRET]  # one request, to the endpoint itself
    assert Recorder.seen == []  # nothing, GET or POST, reached where the 30x pointed


def test_plain_http_to_this_machine_bypasses_every_proxy(mcp_server, recorder, monkeypatch):
    """A proxy (a work laptop's, say) would get a plain-http request whole, header and all: doctor skips it."""
    for var in ("http_proxy", "HTTP_PROXY", "all_proxy", "ALL_PROXY"):
        monkeypatch.setenv(var, recorder)
    for var in ("no_proxy", "NO_PROXY"):
        monkeypatch.delenv(var, raising=False)
    n, err = doctor.tools_list(mcp_server, "Authorization", SECRET)
    assert (n, err) == (2, None)
    assert Recorder.seen == [] and FakeMCP.seen[-1][0] == SECRET


@pytest.mark.parametrize("value", [SECRET + "\r\n", SECRET + "\n", SECRET + "\0"])
def test_a_credential_with_a_line_break_is_not_sent_or_shown(mcp_server, value):
    n, err = doctor.tools_list(mcp_server, "Authorization", value)
    assert n == 0 and "line break" in err and TOKEN not in err
    assert FakeMCP.seen == []


def test_an_unbuildable_request_never_quotes_the_credential(monkeypatch):
    def bad(*a, **k):
        raise ValueError(f"Invalid header value {SECRET!r}")
    monkeypatch.setattr(urllib.request.OpenerDirector, "open", bad)
    n, err = doctor.tools_list("https://mcp.example.invalid/mcp", "Authorization", SECRET)
    assert n == 0 and TOKEN not in err
