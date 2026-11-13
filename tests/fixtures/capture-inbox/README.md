# Capture batch fixture (KAN-458)

A knowledge repository whose inbox holds 3 meeting transcripts and 10 chat threads. Four threads qualify for
extraction (two with five or more messages, two with a decision word); six do not. `tests/test_capture_batch.py`
runs the batch on a copy. Verify by hand:

```sh
python scripts/capture_batch.py run --repo tests/fixtures/capture-inbox --dry-run --no-pull
ai-dlc knowledge check tests/fixtures/capture-inbox
```
