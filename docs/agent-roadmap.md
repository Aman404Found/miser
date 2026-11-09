# Building an agent like Buffy: what MISER is missing

This document answers three questions: why a general agent can read and edit many
files while MISER struggles with one, why its tool calling looks strong, and what
MISER would need — in phases — to behave the same way.

It is deliberately concrete. Every claim below is about a specific tool signature
or a specific place in MISER's loop, not about model quality.

---

## 1. The honest framing: this is a tool-surface problem, not a model problem

MISER and Buffy can be pointed at the same model. When Buffy edits six files and
MISER fails on one, the difference is almost never the model. It is that the
harness gives the model a different problem to solve.

MISER's edit loop asks the model to reproduce file bytes exactly:

```
edit(path, old, new)   →  old must appear exactly once
```

To satisfy that, the model must already *know* the exact bytes. MISER's only way to
learn them is `zoom(path, level=2)` or `recall`, one file and one region at a time,
and the result is formatted as prose-ish text the model has to re-parse. Every
extra file is another round trip, another chance to mis-copy a blank line, and
another full prompt rebuild (MISER rebuilds the system prompt and history on each
step).

Buffy's edit loop removes the recall step:

```
read_files([{path, offset, limit}, ...])   →  exact bytes, several files, numbered
str_replace(path, [{old, new}, {old, new}]) →  all replacements or none
```

Three properties do the work:

1. **Retrieval is batched and windowed.** The model asks for `pricing.py:1-80` and
   `test_pricing.py:1-120` in one call and gets back exactly the lines an edit
   needs, with line numbers. Nothing is copied from memory.
2. **Edits are transactional and plural.** Several replacements in one file, or
   several files, commit together. A partial failure rolls back instead of leaving
   a half-applied change the model then has to reason about.
3. **Failure is diagnostic.** A failed match returns the nearest region and the
   line number, which is a *next action*, not a dead end. This is the single
   biggest difference in practice: MISER's failed edit burns a turn; Buffy's failed
   edit usually succeeds on the next attempt because the error text is actionable.

MISER already has this instinct in `Workspace` (whitespace-tolerant matching,
nearest-line diagnostics, exact-edit safeguards). What it lacks is *breadth*: one
file per call, no batched read, no glob/search primitive that returns line windows.

### Why the tool calling looks strong

Not because the model is smarter. Because the tools are shaped so that correct use
is the easy path:

- **Small, orthogonal schemas.** `read_files`, `str_replace`, `write_file`,
  `run_terminal_command`, `code_search` do not overlap. The model rarely has to
  pick between two plausible tools.
- **Results are self-describing.** Each result says what it did and what it did not
  do (bytes read, truncation, exit status, matched line numbers). The model can
  check its own work without another call.
- **Independent calls run together.** Reading five files is one step, not five.
  Fewer steps means less context drift and fewer chances to lose the thread.
- **Verification is part of the loop, not an afterthought.** After edits, the
  harness re-reads and runs a check, and reports the real exit status. The model is
  never told "looks fine".
- **Errors are instructions.** "Old string not found; nearest match at line 41" is
  a different class of message than "edit failed".

The transferable lesson: measure tool design by *how many turns a competent model
needs to succeed*, and by *how often a single mistake is recoverable in one turn*.

---

## 2. Tools MISER does not have

MISER currently exposes 11 tools: `repo_map`, `list_files`, `search`, `zoom`,
`recall`, `edit`, `edit_batch`, `apply_patch`, `blast_radius`, `run_tests`,
`verify_claim`. They run serially, one call at a time, in `for call in calls:`.

| Capability | Buffy tool | MISER today | Effect of the gap |
| --- | --- | --- | --- |
| Batched, windowed reads | `read_files` (list of paths, `offset`/`limit`) | `zoom` (one region), `recall` | N files cost N turns |
| Multi-file atomic edit | `str_replace` (list of replacements) | `edit_batch` (same file), `apply_patch` (diff only) | Cross-file changes need several model turns |
| Whole-file write | `write_file` | none (must diff against existing content) | New files are awkward |
| Regex content search | `code_search` with `flags`, `cwd`, context lines | `search` (narrower) | Discovery is slower and noisier |
| Path globbing | `glob` | `list_files` | Cannot ask "all `tests/**/*.py`" directly |
| Directory listing | `list_directory` | `list_files` | No cheap structural probe |
| Command execution | `run_terminal_command` (SYNC/BACKGROUND, exit status, logs) | `run_tests` (fixed acceptance command only) | No lint, no typecheck, no repro scripts |
| Task tracking | `write_todos` | none | Long tasks lose the plan |
| Web search / fetch | `web_search`, `read_url` | `web_search`, `fetch_url` (Phase 5) | Live Tavily/fetch run still unrecorded |
| Doc lookup | `context7` | none | API details must come from memory |
| Memory / knowledge base | `meko` tools | none | No cross-session learning |
| Browser automation | `playwright`, `chrome-devtools` | none | No UI verification |
| Clarifying question | `ask_user` | none | Ambiguity is guessed at, not asked |
| Service discovery | `gravity_index` | none | Integration choices are invented |

Note the deliberate constraint: MISER must not have *model-controlled arbitrary
shell execution*. `run_terminal_command` in the table is therefore not a straight
port — Phase 3 below specifies a supervised variant.

---

## 3. Phases

Each phase is independently shippable and ends with tests. Do not start a phase
before the previous one's acceptance criteria are measured, not asserted.

### Phase 1 — Retrieval breadth

> **Status (2026-11-09): implemented.** `read_many`, `find_files`, and scoped
> `search` (`cwd` + `context`) exist and are covered by tests. The call-count
> acceptance measurement has not been recorded yet.

Add `read_many(paths)` (list of `{path, offset, limit}`, per-file byte budget,
explicit truncation markers) and `find_files(pattern)` (glob with ignore rules).
Extend `search` with context lines and a required `cwd` so results stay scoped.

**Acceptance:** a three-file task completes with fewer tool calls than today, and a
five-file read is one call. Both counted from the ledger, before and after.

### Phase 2 — Edit reliability

> **Status (2026-11-09): implemented.** `write_file` creates new files through the
> same guard/approval path; `edit_batch` was already atomic with rollback; failed
> edits now include the nearest matching numbered region. The failure-rate
> acceptance measurement has not been recorded yet.

Generalize `edit_batch` to accept replacements across multiple files as one
transaction with rollback, and add `write_file` for new files. Keep the exact-hash
preconditions and symlink checks. On failure, return the nearest matching region
with line numbers (MISER already computes this — surface it in the tool result).

**Acceptance:** edit-failure rate on the evaluation tasks drops, and no failed
batch leaves a modified file behind (verified by hash).

### Phase 3 — Supervised execution

Add a command tool whose binaries come from a user-approved allowlist
(`python3 -m unittest`, `pytest`, `ruff`, `mypy`, `node --test`, `git status`,
`git diff`), each invocation shown for approval unless the user has opted into
that specific command. Capture stdout, stderr and the real exit status. Support a
background mode with a log file and an explicit stop.

This is the phase where the no-arbitrary-shell rule must be enforced in code, not
by prompt: reject anything not on the allowlist, reject shell metacharacters,
never run through a shell.

**Acceptance:** allowlisted commands run; a metacharacter or unlisted binary is
refused with a clear message; exit status is preserved through the pipeline; a
background job is startable and stoppable.

> **Status (2026-11-09): implemented.** `miser/execution.py` holds the allowlist,
> metacharacter rejection, `shell=False` spawning, per-invocation approval (with
> "always" for an exact argv), real exit status, sanitised child environment, and
> background jobs with a log file plus stop. `tests/test_execution.py` covers every
> clause of the acceptance sentence above (8 tests; 208 total passing). The headless
> `run` path has no approval channel and therefore refuses, by design. What is not
> recorded: a model-driven task using the tool, since no live run has needed it yet.

### Phase 4 — Planning and progress

Add `write_todos` (an ordered list the model rewrites as it advances) and require
the plan to be re-emitted after each completed step. This is what keeps a
twenty-turn task from drifting.

**Acceptance:** a multi-step task's todos always reflect completed work at the end
of the run, and the transcript shows one update per step, not a single dump.

> **Status (2026-11-09): implemented.** `miser/todos.py` holds `TodoList` with
> validation, normalisation, a revision counter and `stale_checks`.
> `write_todos` is the 16th tool and requires the whole list on every call.
> `build_messages()` re-injects `todos` on every step, so the plan stays in context
> even if the model omits it, and `run_agent` sets `plan_reminder` when a turn did
> tool work without re-emitting the list (only while another step remains).
> The terminal and TUI render one compact checklist per successful call rather than
> a running dump. `tests/test_todos.py` covers validation, revision, reminders and
> rendering (14 tests; 222 total passing). What is not recorded: a live model-driven
> multi-step task using the tool.

### Phase 5 — Knowledge and web

Formalize `web_search` and `fetch_url` with the untrusted-content contract MISER
already uses in `verify_claim`: fetched text is data, never instructions, and is
labelled as such in the prompt. Add documentation lookup for pinned library
versions.

**Acceptance:** a task requiring an external API detail cites the fetched URL, and
injected instructions in a fetched page do not change tool selection (tested with
a fixture page).

> **Status (2026-11-09): implemented, live acceptance pending.** `miser/web.py`
> holds `WebAccess` (`search`, `fetch`), URL policy in `check_url`, redirect
> re-validation, byte/char caps and an `HTMLParser`-based extractor. `web_search`
> and `fetch_url` are the 17th and 18th tools. Fetched text is always returned in a
> `tool` message with an untrusted label, never in the system prompt, and the system
> prompt says page content is data rather than instructions. `tests/test_web.py`
> covers the guard, redirects, truncation, labelling, shared budget and tool wiring
> (18 tests; 240 total passing). The guard is application-level: hostnames are not
> resolved, so it is not a DNS-rebinding-proof sandbox. What is not recorded: a live
> model-driven task with a real Tavily search and a real page fetch.

### Phase 6 — Parallelism and context

Run independent read-only tools concurrently and stream their results as they
arrive. Tighten compaction: summarize rather than truncate, and compact before the
75% mark when a tool result was large.

**Acceptance:** wall-clock time for a multi-read step drops measurably, and a long
session keeps its earlier decisions in context.

### Phase 7 — Evaluation harness

A small fixed task suite (edit a bug, add a test, refactor across two files, fix a
lint error) run against a real gateway, recording: turns, tool calls, edit
failures, tokens, wall clock, and whether the acceptance command passed.

**Acceptance:** a `docs/benchmark-results.md` table produced by one command, with
real numbers and a stated date, replacing any estimates.

---

## 4. What to do first

Phase 1 plus Phase 2. Everything else is convenience; batched reads and
transactional multi-file edits are the two changes that convert MISER's "one file,
retry on failure" loop into Buffy's "many files, verify once" loop. Phase 3 is the
highest-value *new* capability, but it carries the most risk because it touches the
shell-execution rule, so it should land after the edit path is trustworthy.
