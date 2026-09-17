# `dibs` — a file-reservation lock for concurrent coding agents

Design proposal, not yet built. Follow-on from
[`AGENT_TOOLING_GAPS.md`](AGENT_TOOLING_GAPS.md) §1 — this is that gap, spec'd
out enough to actually build. Intended as its own repo, not part of logjam:
nothing about it is logistics-specific.

## Problem

During one session on this repo, several background coding agents ran
concurrently against a single working tree — no branches, no PRs per task,
just parallel processes reading and writing the same files. Twice, two agents
independently needed to edit the same file at close to the same time
(`scripts/build_pdfs.py`'s slug list; `scripts/reports/_brief.py`'s chart
renderer). Both were avoided only because a human-in-the-loop coordinator
noticed the overlap in advance and sequenced the work by hand — not because
any tool caught it.

Git's answer to concurrent writes is "merge conflict, resolve it after the
fact." That's a reasonable model for humans on separate branches working over
hours. It's a poor fit for agents that may both read-modify-write the same
file within seconds of each other, in the same working tree, with no branch
isolation — by the time there's a conflict to resolve, one agent may have
already produced a result built on the false assumption that its edit landed
cleanly.

## Goal

Let an agent **claim** a file before writing to it, so a second concurrent
agent is told "in use, by whom, since when" up front instead of racing it
silently. Prevent the collision from being scheduled at all, rather than
cleaning up after it happens.

## Non-goals (v1)

- **Not a distributed lock.** Single machine, single working tree, multiple
  local processes. No network, no server, no multi-machine coordination.
- **Not AST-aware.** File-level claims only. Both real collisions this
  session were file-level; sub-file (e.g. "I'm only touching this one
  function") granularity is a plausible v2, not a v1 requirement chasing a
  problem not yet observed twice.
- **Not a replacement for git.** `dibs` governs who may *start* editing a
  file right now; git still governs history, diffs, and merges as it always
  has.
- **Not enforcement against uncooperative processes.** Like `flock`, this is
  advisory: it only stops agents that check before writing. A process that
  ignores `dibs` can still write. The target integration point (an
  editor-tool hook, see below) is what makes checking automatic rather than
  optional.

## Design

### Storage

A directory of per-path lock files under `.git/dibs/` (never committed, lives
alongside git's own local state, cleaned up automatically like other git
internals). One JSON file per claimed path, named by a hash of the repo-
relative path:

```json
{
  "path": "scripts/build_pdfs.py",
  "holder": "agent-a0d7a8f3",
  "claimed_at": "2026-09-15T19:41:02Z",
  "pid": 48213,
  "note": "adding carrier_routes_2026 to _BRIEF_SLUGS"
}
```

`.git/` is already the natural home for local, non-committed, repo-scoped
process state — no new dotdir convention to invent, and it's already
gitignored by construction.

### CLI

```
dibs claim <path> [--note "why"]      # exit 0 if free or already yours;
                                        # exit 1 with holder info if held
dibs release <path>                    # no-op if not held by you
dibs release --all                     # release everything this pid holds
dibs status [path]                     # list current claims, or check one
dibs sweep                             # release claims whose pid is dead
                                        # (stale-lock cleanup)
```

Exit codes matter more than output formatting here — the primary caller is a
hook script, not a human terminal.

### Hook integration (the actual point of building this)

Claude Code (and presumably comparable harnesses) support a `PreToolUse` hook
that can block a tool call. The intended integration:

- **`PreToolUse` on `Edit` / `Write` / `NotebookEdit`**: run `dibs claim
  <path>`. If it fails, block the edit and surface the holder + note to the
  agent, so it can wait, pick a different file, or ask the coordinating
  session to resolve it — instead of silently racing.
- **Session end / `Stop`**: run `dibs release --all` for that session's pid,
  so a crashed or finished agent doesn't leave a stale claim blocking
  everyone else. `dibs sweep` is the backstop for the case where even that
  doesn't fire cleanly.

This means v1 needs zero changes to any harness — it's a couple of hook
script entries in `settings.json` plus the `dibs` binary itself. That's
deliberately the whole point: the value is in being trivially adoptable, not
in a clever locking algorithm.

### What "in use" should tell the blocked agent

Not just "locked" — enough to act on:
- who holds it (which agent/session id)
- how long they've held it
- their stated `--note`, if any (what they're doing to that file)

That's enough for a coordinator (human or another agent) to decide: wait,
reassign the work, or intervene.

## Open questions

- Does the *coordinator* (the process launching parallel sub-agents) need its
  own `dibs`-aware scheduling primitive, or is "sub-agent hits a claimed file,
  reports back, coordinator retries later" sufficient? Leaning toward the
  latter for v1 — simpler, and matches how this session actually recovered
  from the risk (sequencing after the fact), just automated.
- Should `dibs claim` support a short blocking wait (`--wait 30s`) instead of
  failing immediately, for the common case where the holder is about to
  finish? Probably yes eventually, not essential for v1.
- Packaging: a single dependency-free binary (Go? Rust?) would make the hook
  script trivial and fast; a Python script is faster to prototype but adds a
  runtime dependency to every repo that adopts it. Leaning toward starting in
  whichever language ships a working v1 fastest, then reconsidering once the
  hook-integration shape is proven.

## Why this and not v2 features first

File-level, advisory, single-machine, hook-triggered — every corner cut here
is a corner that wasn't the actual problem observed this session. The value
is in shipping the smallest thing that would have caught both real collisions
today, wired into the one integration point (an editor-tool hook) that makes
it automatic rather than another manual discipline to remember.
