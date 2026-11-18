# Changelog fragments

Each PR adds its entry as `changes/<KEY>.md` (its ticket key) and never edits a shared changelog, so parallel PRs
can't conflict on it. The section is Changed unless the name says otherwise: `<KEY>.added.md`, `.fixed.md`,
`.removed.md`, `.deprecated.md` or `.security.md`. Write the entry as one or more `- ` bullets.
