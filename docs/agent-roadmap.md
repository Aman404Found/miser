# Building an agent like Buffy: what MISER is missing

This document answers three questions: why a general agent can read and edit many
files while MISER struggles with one, why its tool calling looks strong, and what
MISER would need — in phases — to behave the same way.

It is deliberately concrete. Every claim below is about a specific tool signature
or a specific place in MISER's loop, not about model quality.

---

## 1. Original hypothesis: tool design affects task performance

Harness design can change task performance, but this repository has no controlled
MISER-versus-Buffy comparison establishing causation. The analysis below is a
historical design hypothesis, not a measured model-quality conclusion.

MISER's edit loop asks the model to reproduce file bytes exactly:

```
edit(path, old, new)   →  old must appear exactly once
```

To satisfy that, the model must already *know* the exact bytes. The original tool surface used `zoom(path, level=2)` or `recall`, one file and
one region at a time (current MISER also supports `read_many`),
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
nearest-line diagnostics, exact-edit safeguards). The breadth gaps described here motivated the now-implemented batched reads,
globs and scoped context search.

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

## 2. Current tools and remaining gaps

Current MISER has a 19-tool catalog, including `ask_user`, with 9/12/19 tools exposed
for inspect/research/coding profiles. Only batches made entirely of `READ_ONLY_TOOLS`
run concurrently; edits, tests, commands, verification and todo updates stay sequential.

| Capability | Current implementation | Remaining limitation |
| --- | --- | --- |
| Batched reads | `read_many`, up to 8 windows | Bounded output can truncate |
| Multi-file changes | `edit_batch`, `apply_patch` | Atomic per file; best-effort rollback, not crash-atomic |
| New files | `write_file` | Existing files require checked edits |
| Discovery | `search` with scope/context, `find_files` | Literal search; no regex content search |
| Commands | `run_command`, allowlisted argv and fresh approval | Headless mode refuses; not an OS sandbox |
| Plans | `write_todos` | Prompt reminders cannot prove tasks completed |
| Task clarification | `ask_user`, numbered choices or free text | Live task resumes after an answer; headless/declined questions stop as needs_input |
| Web | `web_search`, `fetch_url`, `verify_claim` | DNS destinations not pinned; labels do not prove injection resistance |
| External capabilities | Opt-in HTTP MCP discovery/calls with host allowlists and fresh approval | Read-only subset; no live service connection verified; browser absent |

MISER must not have *model-controlled arbitrary shell execution*. Its command
tool is the supervised variant described in Phase 3 below.

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
> same guard/approval path; `edit_batch` stages writes with best-effort rollback; failed
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
`git diff`), each invocation shown for fresh approval. Capture stdout, stderr and the real exit status. Support a
background mode with a log file and an explicit stop.

This is the phase where the no-arbitrary-shell rule must be enforced in code, not
by prompt: reject anything not on the allowlist, reject shell metacharacters,
never run through a shell.

**Acceptance:** allowlisted commands run; a metacharacter or unlisted binary is
refused with a clear message; exit status is preserved through the pipeline; a
background job is startable and stoppable.

> **Status (2026-11-09): implemented.** `miser/execution.py` holds the allowlist,
> metacharacter rejection, `shell=False` spawning, fresh per-invocation approval (no cached approval), real exit status, sanitised child environment, and
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

> **Status (2026-11-09): implemented; model-driven fetch recorded, injected-instruction
> case unit-tested only.** `miser/web.py`
> holds `WebAccess` (`search`, `fetch`), URL policy in `check_url`, redirect
> re-validation, byte/char caps and an `HTMLParser`-based extractor. `web_search`
> and `fetch_url` are the 17th and 18th tools. Fetched text is always returned in a
> `tool` message with an untrusted label, never in the system prompt, and the system
> prompt says page content is data rather than instructions. `tests/test_web.py`
> covers the guard, redirects, truncation, labelling, shared budget and tool wiring
> (18 tests; 240 total passing). The guard is application-level: hostnames are not
> resolved, so it is not a DNS-rebinding-proof sandbox. Live services were exercised
> by a host script: a real Tavily search returned 3 hits, and real fetches of
> `docs.python.org/3/library/pathlib.html` and `realpython.com/python-pathlib`
> returned HTTP 200 and were converted to capped text; the second followed a live
> redirect, confirming redirect re-validation. A Stack Overflow hit returned HTTP 403
> (site bot protection) and the tool surfaced the error rather than retrying.
> Recorded live afterwards: session `runs/session-e4d476853be7` answered from a
> fetched `docs.python.org` page (answer reportedly cites the URL) in 4 model requests,
> 4 tool calls and 18,777 provider tokens. Citation alone does not prove correctness;
> the former 3.10 `read_text(newline=...)` claim conflicts with this host's 3.12.3 API.
> Unit tests verify untrusted labels and returned text, not whether a model ignores
> injected instructions. That behavioral acceptance remains unverified. The host
> cannot bind a local fixture listener; simulated transport needs no listener.

### Phase 6 — Parallelism and context

Run independent read-only tools concurrently and stream their results as they
arrive. Tighten compaction: summarize rather than truncate, and compact before the
75% mark when a tool result was large.

**Acceptance:** wall-clock time for a multi-read step drops measurably, and a long
session keeps its earlier decisions in context.

> **Status (2026-11-09): implemented and measured.** A step whose calls all parse,
> all belong to `READ_ONLY_TOOLS`, and number two or more now runs on a small worker
> pool (`MAX_PARALLEL_TOOLS=8`) inside `run_agent`; starts are announced on the main
> thread in model order, completions arrive via `as_completed`, activity results are buffered into model order, and tool messages,
> `memory.observe` and the `tests_passed` early exit are emitted in call order, so
> the transcript is identical to a sequential step. `run_tests`, `write_todos`,
> edits, `run_command` and `verify_claim` stay sequential. A `tool_batch` ledger
> event records tool names, count, step and parallel flag; it has no batch-latency field.
>
> Compaction now stores a structured digest (`compact_digest`) of each compacted
> tool output plus a bounded `decisions` deque, and the decisions are re-injected
> only when a real compaction happens. The threshold adapts: when the largest tool
> output exceeds 12% of the budget, compaction fires at 55% of the budget instead of
> 75%. `Ledger` and the web budget take locks (`RLock`, `Lock`) so parallel tools
> cannot race the token counters or exceed the shared search budget.
>
> **Measurement (honest):** with real local `zoom` calls, parallelism is *not*
> faster — median wall clock for 1/2/4/8 calls was 0.5/0.9/2.3/6.6 ms sequential
> versus 0.4/1.5/3.6/10.3 ms parallel, because thread start-up dominates work that
> already takes microseconds. With a simulated 150 ms per-call latency (labelled,
> not a real service), four calls took 601 ms sequential versus 151 ms parallel,
> about 4.0×. So the win is for network-bound tools (`web_search`, `fetch_url`),
> and local reads pay a small overhead; outputs were reported byte-identical either way.
> Simulated latency does not establish a speedup for a real remote service.
> 249 tests pass (`python3 -m unittest discover -s tests -q`). No live concurrency
> timing was recorded against a real remote tool because this host cannot bind
> sockets.

### Phase 7 — Evaluation harness

A small fixed task suite (edit a bug, add a test, refactor across two files, fix a
lint error) run against a real gateway, recording: turns, tool calls, edit
failures, tokens, wall clock, and whether the acceptance command passed.

**Acceptance:** a `docs/benchmark-results.md` table produced by one command, with
real numbers and a stated date, replacing any estimates.

> **Status (2026-11-09): implemented and measured; golden thresholds not met.** The
> harness was already present (`miser/evaluation.py`, `miser evaluate --demo <lang>`),
> so this phase recorded real runs rather than new harness code. Three runs used the
> real CLI, the real gateway and provider-reported usage (`usage_complete: true`,
> `failed_model_requests: 0`, no compactions or fallbacks). Python and JavaScript both
> ended `tests_passed` with one model edit and five model calls — 15,000 and 14,937
> provider tokens, 41.3 s and 41.8 s. A fourth attempt with the default 12,000-token
> budget ended `budget_exhausted` after four orientation calls and no edit.
>
> The measured result is that the fixed golden limits
> (`GOLDEN_LIMITS = {"max_model_calls": 4, "max_provider_tokens": 6000}`) are **not**
> reachable with this model and tool surface: `golden_tasks_passed: 0`, so
> `miser evaluate` exits 1 even on the two solved runs. The receipt's
> `request_component_tokens_estimate` is cumulative across requests, not per request;
> dividing by the call count shows roughly 2,800 estimate tokens of fixed overhead per
> call (663 instructions + 1,696 tool definitions), and observed provider prompts were
> 2.4–3.4k per call, so a 6,000-token ceiling allows about two calls.
>
> **Coverage gap, stated honestly:** the fixture suite now recorded is the single
> bug-edit task in both languages. The add-test, cross-file refactor and lint-fix
> fixtures described in this phase are not recorded yet, so the table does not cover
> them. 249 tests pass; the phase was documentation plus recorded runs, so no test
> count changed. See [`docs/benchmark-results.md`](benchmark-results.md).

---

## 4. What to do next

Phases 1–7 have implementations; several acceptance measurements remain missing.
Use [the audit report](audit-report.md) to prioritize unresolved safety boundaries,
then measure failure recovery and add real cross-file tasks before claiming parity.

### Optimization and capability queue (2026-11-09)

Follow-up: live-session context now spans local reads and agent tasks as well as
conversation; exact previous-message queries run locally. The screenshot's
four-line request wording also bypasses models/tests. Terminal code wrapping,
streamed fences, styled Unicode text and transcript resize/scroll behavior have
regression coverage. See implementation-status.md for bounds and measured local
smoke timings; no provider latency or cache improvement is established.

The slow README example was a routing failure: its recorded run spent 12.942 seconds
in baseline tests and 59.361 seconds across three model completions (including retry
handling), totaling about 72.3 seconds. The two file tools each took about 1 ms.
Its ledger reports 7,265 provider tokens; these are recorded numbers, not estimates.

| Order | Capability | State / concrete next increment |
| --- | --- | --- |
| 1 | Local deterministic file reads | Implemented: simple display/first-lines requests bypass models/tests, retain guards and record a local receipt. Symmetric M logo plus explicit MISER caption fixes the N-like glyph. |
| 2 | Capability-aware model requests | Implemented: inspect/research/coding profiles expose 9/12/19 tools. Read-only loops inspect actual evidence, skip tests/architect calls and reject edits/commands/tests at dispatch. CLI --profile overrides language-based inference. |
| 3 | Clarification during a task | Implemented: ask_user pauses line/TUI tasks for numbered options or free text, then continues with the answer. Three-question limit; no mixed batches; headless/declined input stops with needs_input. |
| 4 | Persistent project knowledge | Implemented: host-managed /remember, /memory, /forget plus CLI equivalents; bounded per-repository facts load as untrusted data. Optional source hashes exclude stale facts. No automatic learning, model writes or loading of development memory.md. |
| 5 | External tool discovery/integrations | Implemented HTTP MCP read-only subset: explicit external host config, discovery, allowlists, fresh approval, untrusted output and bounded JSON/SSE. No subprocess servers or runtime dependencies. Live server/Meko connection remains unverified; see [MCP guide](mcp.md). |
| 6 | Browser/UI verification | Optional host-controlled browser inspection/screenshots and meaningful UI acceptance checks. No browser tool currently exists in MISER. |
| 7 | Delegated workers | Budgeted, observable read-only research/review workers before any concurrent editing; current parallel tool calls are not independent agents. |

These are separate increments, not a claim that all are implemented. Preserve the
audit's unresolved DNS/filesystem isolation work alongside this capability queue.
Do not loosen command approval or edit safeguards to imitate broader tool access.

Local size diagnostics for the profiles (UTF-8 bytes / 4 estimates, not billing):
coding tool definitions 1,808 tokens + instructions 726; inspect 789 + 218;
research 1,064 + 218 (after the project-knowledge instruction was added). These exclude user/state/history/framing and do not establish
provider token savings, model reliability or real wall-clock speedup. New coverage
uses scripted provider responses, synthetic usage and simulated TUI key events;
no live model/service evaluation was made for these capabilities.

Persistent project facts add context only when saved/enabled: at most 8 facts and
3,000 serialized UTF-8 bytes from a 20-fact, 400-character-per-fact store. Selection
uses keyword overlap and recency. Source-linked entries require unchanged readable
UTF-8 contents; stale entries remain reviewable but are excluded. This is local
POSIX persistence, not cloud/Meko sync, semantic truth verification or replay of
old model conversations. Model requests include the actual selected context in
their normal budget diagnostics; no extra summary/model call is added.

### Native terminal application (2026-11-10)

The interactive CLI now launches Textual with native layout, Markdown, scrolling,
multiline input and modal approvals. The previous Rich row UI is superseded.
Actual CLI PTY verification covers 80×24, 120×36 and 160×45 using a simulated
provider and real backend edits/tests; a separate unmodified CLI check covers
local actions without provider calls. See [UI evidence](terminal-ui.md). Browser
automation and delegated workers in the capability queue remain unimplemented.

### Explicit latency controls (2026-11-10)

Implemented route/timing diagnostics and /timing. /checks manual is an opt-in host
policy for skipping automatic tests/architect, with edited_unverified outcomes;
/checks required remains default. Existing guards and evaluation thresholds remain.
Guarded file deletion and the bounded /files on workflow are now implemented; see
[file-operation evidence](file-operations.md). Next: carefully invalidated verification
selection/cache and live task-matrix measurements. Provider 429 latency is
not solved by local timing or UI changes. See terminal-ui.md for verification.
