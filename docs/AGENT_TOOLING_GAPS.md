# Tooling gaps: git/GitHub for multi-agent development

Notes from a single working session on this repo (2026-09-15) that ran several
background coding agents concurrently against one working tree — no branches,
no PRs per task, just parallel processes reading and writing the same files.
Git's model assumes a human on a branch; that assumption broke in a few
specific, recurring ways. Recorded here because the friction was real and
repeatable, not hypothetical.

## 1. A file-reservation layer for concurrent automated edits

**What happened:** two background jobs each needed to append their own entry
to the same tuple in `scripts/build_pdfs.py` (`_BRIEF_SLUGS`), and separately,
two more each wanted to extend the same chart-rendering function in
`scripts/reports/_brief.py`. Both were caught by sequencing the jobs by hand
and telling each one explicitly which files were off-limits — not by any
tooling.

**Why git doesn't cover it:** git's answer to concurrent writes is "merge
conflict, resolve it after." That's fine for humans on separate branches
working over hours. It's a bad fit for agents that might both read-modify-write
the same line within seconds of each other, in the same working tree, with no
branch isolation — by the time there's a conflict to resolve, one agent may
have already produced a partially-inconsistent result built on the assumption
its edit landed cleanly.

**What would help:** an advisory lock keyed to a file, or even finer — an AST
node ("I'm appending to this specific tuple/list") — that a coordinating
process checks before dispatching parallel work. Not a merge tool; a
pre-flight check that prevents the collision from being scheduled at all.

## 2. Provenance-aware `git status`

**What happened:** repeatedly needed to work out "which of these uncommitted
changes are from this session versus pre-existing WIP that was sitting there
before I started" — four files (`_geo.py`, `build_geo_assets.py`, two geo
resource JSONs) stayed modified-but-uncommitted across the *entire* session
because they predated it and weren't mine to fold in blindly. Every commit
required re-running `git status` / `git diff --stat` and reasoning about it
from scratch.

**Why git doesn't cover it:** git tracks *what* changed, not *who* changed it
or *when relative to "now" it became dirty*. There's no native way to ask "show
me only what changed in the last hour" or "group these hunks by whichever
process touched them."

**What would help:** a `git status` mode that groups hunks by originating
session/actor, or at minimum by a coarse heuristic like "modified before vs.
after this session's start timestamp." Even a lightweight local log of "which
tool invocation last wrote to this path" would've turned several minutes of
diff archaeology into a single lookup, repeated maybe eight times this
session.

## 3. Semantic diff for generated artifacts

**What happened:** PDFs and JSON data payloads were regenerated roughly a
dozen times over the session (every report rebuild). `git diff` on a PDF is
`Bin 482414 -> 482414 bytes` — no signal at all on whether the rebuild changed
real content or just re-encoded identically.

**Why git doesn't cover it:** git *does* support this in principle
(`textconv` / diff drivers in `.gitattributes`), but it's opt-in, per-repo
configuration that essentially nobody sets up proactively, and it wasn't in
place here either.

**What would help:** semantic diff drivers that are default-on for common
generated types — PDF → extracted-text diff, minified/pretty-printed JSON →
structural diff that ignores key reordering and whitespace. The goal: "did
this rebuild actually change anything a reader would notice" answerable at a
glance instead of by re-reading the whole file.

## 4. Diff review scaled to claims, not lines

**What happened:** background agents returned reports like "I built X,
verified Y, tests pass" across changesets of 300-1600+ lines each (see
`git log` this session — five separate multi-hundred-line feature commits in
one afternoon). The only way to actually check those claims was re-deriving
them from the diff by hand — reading the CLI addition to confirm the example
invocation in the report was real, re-running the map-data spot checks myself,
etc.

**Why git doesn't cover it:** `git diff` / GitHub's PR view show *what changed
textually*; neither extracts or verifies the *behavioral claims* a changeset
makes. That gap is exactly where an agent's self-report can drift from what
the code actually does, and it doesn't show up as a diff artifact.

**What would help:** a review mode that extracts discrete claims from a
changeset's own description ("new CLI command `X` exists and returns `Y` for
input `Z`"; "test file covers case `W`") and mechanically checks each one —
runs the command, greps for the test — rather than relying on a human or
reviewer to skim hundreds of added lines and trust the summary.

## Priority

(1) is the one that would have mattered most concretely today — it's the only
one of the four that represents an actual near-miss (two jobs wanting the same
file at the same time) rather than accumulated friction. (2) and (4) were
steady, lower-grade time costs across the whole session. (3) came up but never
actually caused a wrong decision, just wasted a few `git diff` calls that
returned nothing useful.
