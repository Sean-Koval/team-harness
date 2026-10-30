Specify and sketch how hangar (the run plane) asks the governed workspace (Tower, the govern plane) for approvals.
Nothing calls the new code yet; it is the contract, a client skeleton and contract tests.

1. `docs/specs/0015-governance-decision-point.md` (indexed in `docs/specs/README.md`): the five kinds `job.release`,
   `tool.call`, `landing.approve`, `egress.request`, `secret.request` (wire kinds `hangar.<kind>`); the
   `hangar.decision/v1` request and response; HTTP handling (any 5xx, even `503 {"decision":"deny"}`, means
   unavailable, not a policy deny); idempotency, signers, status and withdraw, dry run; timeouts (2 s connect, 5 s
   total, a circuit breaker); the fail-closed table and modes (`off`, `shadow`, `enforce`, per kind) with two-admin
   break-glass; signed events. Its JSON examples are machine-read: each in a ```json block right after an
   `<!-- contract: request -->`, `<!-- contract: response -->` or `<!-- contract: event -->` comment, and they must
   parse with the code below (response examples use approval `A-123`; the event's approval carries receipt `RC-104`).
2. `src/hangar/governance.py`: `SCHEMA`, `KINDS`, `FAIL_CLOSED` (kind -> outcome: `deny` for `tool.call`, else
   `wait`; never `allow`); `DecisionRequest` and `Decision` (pydantic, `from_wire`/`to_wire`; a decision has
   `outcome`, `status`, `source`, `failure`, `retryable`, `reason`, `approval_id`); `LocalDecisionPoint` (wraps
   `approvals.can_decide`); `HttpDecisionPoint(url, credential, client=None, timeout=5.0, connect_timeout=2.0)` with
   `decide`, `status(approval_id, kind=)`, `withdraw`: never an allow on any error (unreachable, timeouts, 5xx, 429,
   401/403, 400/422, bad JSON, unknown decision, allow without receipt, wait without approval, bad times or status),
   each a `fail_closed` decision with a failure class and `reason` starting `approval service unavailable`, a 401
   retried once with a fresh token; `StaticCredential`; `GovernanceRouter(local, http, modes)` (enforce needs a URL);
   `parse_modes(default, overrides)`; `BreakGlass`; `wait_for` (backoff, woken early by an event, fails closed at the
   deadline); `args_hash(args)` = sha256 of `json.dumps(args, sort_keys=True, separators=(",", ":"), default=str)`;
   `idempotency_key(kind, ...)` (`hangar:job:<job>:release`, `hangar:job:<job>:landing:<head_sha>`,
   `hangar:session:<s>:tool:<request>`, `hangar:session:<s>:secret:<request>`); `sign_event`, `verify_event(secret,
   headers, body, seen, now=)` over `X-AW-Signature` (`t=<unix>,...` HMAC) and `X-AW-Event-Id`, raising
   `EventRejected` for `replayed`, `stale` (over 300 s), `bad signature`, `unsigned`, `malformed`, `no webhook
   secret`; `rfc3339`, `parse_time`.

Contract tests run against a fake workspace over `httpx.MockTransport`.
