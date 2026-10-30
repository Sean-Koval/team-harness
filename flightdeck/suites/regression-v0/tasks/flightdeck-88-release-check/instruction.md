flightdeck has no release process. Prepare its first tagged release:

- Add `CHANGELOG.md` with an `## Unreleased` section and a section for the current version, headed `## v<version>`.
- Add `scripts/release_check.py`, importable as a module, with:
  - `versions(root=...) -> dict`: the version as written in each version source (`pyproject.toml` and
    `src/flightdeck/__init__.py`), so the sources can be compared;
  - `section(version, root=...) -> str`: the changelog section for that version (empty when there is none);
  - `check(tag, root=...) -> (problems, notes)`: for a tag such as `v0.1.0`, the list of problems (each naming the
    file that disagrees, e.g. `pyproject.toml` or `CHANGELOG.md`) and the release notes. A malformed tag gives
    exactly `["'9.9.9' is not vX.Y.Z[-pre]"]`; a version with no changelog section gives exactly
    `["CHANGELOG.md has no '## v0.9.0' section"]`. `root` defaults to the repository.
  - Run as a script with a tag, it fails on problems and prints the notes.
- Add a release workflow that checks a `v*` tag, runs the tests on the tagged commit and publishes the release, with
  actions pinned by SHA, and a short Releasing section in CONTRIBUTING.md.

Keep the version sources and the changelog consistent with each other.
