Inbox items embedded in `GET /api/fleet` and its stream are redacted with the broker's redactor, but
`GET /api/inbox` and the `hangar://inbox` MCP resource return item text exactly as written. An agent's question or a
denied command can quote a stored credential (for example a GitHub token held by the broker), which then leaks
through those two reads.

Make both reads return redacted item text, with the same redaction the fleet read uses (don't add a second
redactor). Item ids must stay what they are without redaction, so an acknowledgement that names an id still matches,
and the counts are unchanged. The code is in `src/hangar/` (the inbox module and its callers); `tests/test_inbox.py`
has the existing inbox tests.
