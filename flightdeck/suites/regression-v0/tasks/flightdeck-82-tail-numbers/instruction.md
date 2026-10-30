Airframe's brand book gives every ID a "tail number": hangar shows a job `job-e0123d68` as `HGR-JOB-VDTR`, from
hangar's `src/hangar/tails.py` (a cyrb53 hash written in Crockford base32, no I, L, O or U). flightdeck should
show the same codes with its own prefix, so a reader can match an experiment across the two tools.

- Add `flightdeck.ported.tails`, a port of hangar's `tails.py` (Sean-Koval/hangar on GitHub) with the `FDK` prefix:
  `code(real_id, length=4)` gives the same code hangar gives (`code("job-e0123d68") == "VDTR"`,
  `code("sb-8e7f50c8") == "8AS5"`), and a longer length extends the shorter code; `tail(real_id, kind="EXP")`
  gives `FDK-<kind>-<code>` (an experiment reads `FDK-EXP-...`); `label(real_id)` gives ``<tail> (`<real id>`)``.
- The experiment report's experiment line leads with the tail number and keeps the real ID beside it, for example
  ``FDK-EXP-0531 (`job-expdemo`): candidate (...) against control (...), 12 tasks, ...``.

Ported code follows the repository's rules for `src/flightdeck/ported/` (CONTRIBUTING.md). Run `tests/test_report.py`.
