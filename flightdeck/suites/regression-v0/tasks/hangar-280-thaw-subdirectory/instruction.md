A harness registry can live in a subdirectory of a larger repository (for example `examples/team-harness/`). There,
history lookups fail: `team@stable`, `team@r1` and `team@sha256:...` raise
`ThawError: team@stable: not in the registry; team is at r2` although r1 is in the registry's git history, while a
registry at a repository's root works.

Make a registry in a subdirectory resolve `name`, `name@rN`, `name@sha256:...` and `name@<channel>` from its history
exactly as a root registry does, and make claiming (materializing) a historical lock copy that revision's files
(skills included), with nothing reported stale. Root-level registries must behave as before. The code is in
`src/hangar/harness_thaw.py`; mention the subdirectory case in `docs/harness-lock.md`. Run
`tests/test_harness_thaw.py`.
