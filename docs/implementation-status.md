# Implementation status

## Supervised execution update (Phase 3)

- New 15th tool `run_command` with `action = run | status | stop`. It takes an `argv`
  array, never a command string, and is spawned with `shell=False`; no code path
  reaches a shell.
- Binaries come from an allowlist of prefix rules: `python3 -m unittest`,
  `python3 -m pytest`, `python3 -m mypy`, `pytest`, `ruff`, `mypy`, `node --test`,
  `git status`, `git diff`. Anything else is refused with a clear message.
- Any shell metacharacter in any argument (`; & | < > $ ` \n \r ( )`) is refused
  before execution.
- Each invocation is shown for approval: yes (once), no, or always for that exact
  argv, which then runs silently for the rest of the session. The child process gets
  only a small allowlisted environment, so `.env` credentials never reach it.
- stdout, stderr and the real exit status are returned unchanged; a non-zero exit is
  a result, not an exception.
- `background=true` starts a job with a log file under `.miser/jobs/`; `action=status`
  reports running/exit status and output, and `action=stop` kills the process group.
- Because approval is a real channel, the headless path (`python3 -m miser run`) has
  none and therefore **refuses** `run_command`. This is intentional; only the
  interactive terminal and TUI prompt.
- Local verification: 208 tests passed, including 8 new cases in
  `tests/test_execution.py` covering allowlisted run, preserved non-zero exit,
  metacharacter refusal, unlisted-binary refusal, approval refusal, missing approval
  channel, "always", and background start/status/stop. These use real
  `python3 -m unittest` invocations; no live model requests were made.
- App-level guards are not an OS sandbox.

## Truncated-reply and live-run update

- A reply that stops at the output cap (`finish_reason: "length"`) with no tool call
  now finishes as `truncated`, not as a plain "no more tool calls". The result panel
  says so and the TUI status line reads "output truncated", so a reasoning-model
  cut-off is distinguishable from a considered final answer.
- First real end-to-end smoke run: `runs/smoke-phase12-20261109` ended `tests_passed`
  with 4 model calls, 6 tool calls, 0 failed requests, and 8,948 provider tokens on
  `gemini/gemini-3.5-flash-lite`. Recorded in `docs/benchmark-results.md` as one run,
  not a benchmark. The gateway's `gemini-3.5-flash` route was rate-limited (429);
  `gemini-2.5-flash-lite` is listed but returns 404.
- Local verification at that time: 200 tests passed.

## Session reliability update

- Each interactive coding task now gets fresh read/edit tracking. Prior task edits
  cannot satisfy a later task's success condition. Per-task patches contain only
  that task's changes; session-wide change tracking remains available.
- Undo checks that files still match MISER's last written contents before restoring
  them. Externally modified files are skipped and reported, with undo state retained.
- Context compaction stops without recording a `compaction` event when a pass frees
  no prompt tokens, so receipts no longer report zero-gain compactions as savings.
- Resume imports receipts only when their recorded repository matches the current
  workspace. Receipts without repository metadata are skipped.
- Local verification (at that time): 199 tests passed, including consecutive-task success isolation,
  patch separation, external-edit preservation, and cross-repository resume filtering.
  No live model requests were made for this update.

## Retrieval and edit-surface update

- New `read_many(reads)` reads up to 8 `{path, offset, limit}` windows in one call and
  registers the snapshots, so a batched read can be followed directly by `edit` or
  `edit_batch`. Per-file failures return `{"error": ...}` without aborting the batch.
- New `find_files(pattern, limit, cwd)` globs within the workspace only, skipping
  excluded paths; `**/` also matches zero directories.
- `search` accepts `context` (0–5 lines) and an optional `cwd`; the result shape is
  unchanged unless `cwd` is supplied.
- New `write_file(path, content)` creates a new file through the same guard, approval,
  preview, and undo path as edits. Undo deletes files created this way, and diffs
  render them as `/dev/null → b/path`.
- Zero-match edit errors now quote the nearest matching region with line numbers.
- Local verification: 199 tests, including the new retrieval/write-file cases. No live
  model requests were made for this update.

## Failure rendering and retry update

- A failed task now prints one block. `Terminal.render_task_result` renders either the
  result panel or an `error_block`, never both; the duplicate post-`finally` block is gone.
- 429/503 responses retry the whole model chain up to `MAX_ATTEMPTS = 3` with backoff
  `2s, 5s`, honouring a numeric `Retry-After` capped at 30s. Exhaustion ends the task
  with status `model_unavailable` instead of raising, so completed tool work is kept.
- TUI content sits in one centered column (`MAX_CONTENT_WIDTH = 92`); header, rules,
  transcript, composer and footer share a single gutter, and long lines wrap instead
  of being cropped.

## Scope update

The user requested language flexibility. File search/read/edit and fixed acceptance commands work across text-based languages. Structural depth is staged independently: Python AST first; JS/TS regex structure next. Do not market the product as Python-only.

## Built foundation

- Interactive coding terminal (`miser` or `miser chat`), disposable demo mode,
  slash commands, completion, patch review, and per-task receipts.
- Host-driven acceptance tests after edit batches; verification does not require
  a further model call. Failed check output feeds back into agent state.

- Dependency-free Python CLI and OpenAI-compatible Bifrost HTTP adapter.
- Real tool-calling loop, bounded recent history, usage ledger, budget preflight, and step/search/test limits.
- List/search/zoom/recall/exact edit tools and clearly labelled approximate blast radius.
- Test commands fixed by the user, conventional acceptance-file protection, timeouts, traversal/symlink checks.
- Actual before/after Python and JavaScript tool demos, explicitly scripted and not benchmarks.
- Tavily candidate-evidence adapter and version-scoped evidence card format.
- Optional provisional model review of one claim, with URL/quote/version-anchor validation,
  abstention on malformed reviews, and model usage in the shared ledger.
- Disposable live fixture smoke tests and repeatable Python/JavaScript evaluation reports,
  including failed-run spending. These are synthetic fixtures, not an OSS benchmark.
- On-demand repository map, eight bounded tool breadcrumbs, explicit refresh of expired
  reads, and edit recovery hints.

## Full-screen terminal interface

- Default interactive `miser` / `miser chat` now runs a genuine alternate-screen TUI
  (`miser/tui/`): a centered welcome (block logo, composer card, model/budget metadata,
  cwd and shortcuts) and an active conversation (compact header, scrollable transcript,
  persistent composer, status footer). It repaints in place and handles resize, Ctrl+C,
  Ctrl+D, and clean terminal restoration. The line interface remains available with
  `--no-tui`, `--exec`, non-TTY output, `NO_COLOR`/`MISER_PLAIN`, or missing Rich.
- The presentation layer is separated: `miser/tui/screen.py` is pure layout over terminal
  dimensions; `keys.py` decodes raw keys, paste, and control sequences; `input.py` holds
  editable text, history, and completion; `io.py` owns the alternate screen, raw input
  mode, and frame writes; `app.py` owns the event loop, transcript, worker thread, and
  approval handshake. `miser/ui/` still renders Markdown, diffs, panels, and activity.
- The engine keeps session state, commands, approvals, and ledger wiring. Small new seams
  expose an activity listener, a cooperative cancellation event checked between model/tool
  steps, a narrow-width override for transcript output, and persistent prompt history in
  `.miser/history`. No agent or model-client logic was rewritten for the UI.
- Structured activity events (step, model start/end, tool start/result, baseline and
  post-edit acceptance runs, compaction, fallback, architect) drive the footer status and
  transcript. Streaming is SSE-based with `include_usage`; a stream that cannot start falls
  back to a plain request (no double billing), while a stream broken after data stops the
  run with unknown usage and is never resent. `--no-stream` disables streaming.
- Session accounting separates user messages, coding tasks, model requests, tool executions,
  provider tokens, local context estimates, and unknown usage. A session with no requests
  says so instead of showing zero tokens. `/usage`, `/status`, `/diff`, `/receipt`, and the
  other slash commands operate inside the TUI.
- Non-interactive `chat --exec` stays line-oriented; colour, spinner, and prompts degrade
  automatically. `docs/terminal-ui.md` records the architecture, keybindings, fallbacks,
  verification, and limits.

## Completed from the handover roadmap

### Phase 1 — atomic multi-file changes and a unified diff engine

- `Workspace.edit_batch` applies 1–10 exact replacements across files as one transaction:
  every snapshot, version, and match is validated in memory before any write, and a failed
  write restores the pre-batch contents of every file it touched.
- `Workspace.apply_unified_diff` parses standard git-style hunks (counts validated,
  `/dev/null` creation/deletion refused, `\ No newline at end of file` honoured), verifies
  each hunk against the current text, and writes all files through the same atomic transaction.
- Tools `edit_batch` and `apply_patch` are exposed to the model next to `edit`; acceptance
  test paths are guarded for every path in a batch, approval prompts preview each file, and
  `ToolRunner` records cumulative diff previews plus an `edit` ledger event.
- Tests cover multi-file success, validation rollback, write-failure rollback, hunk
  position/ambiguity errors, malformed patches, and tool-level protection/approval.

### Phase 2 — PageRank reference graph repository map

- `miser/repomap.py` extracts definitions (Python AST, JS/TS regex) and identifier
  references, builds a weighted definition/reference graph, and ranks it with a
  standard-library PageRank implementation (`miser.repomap.pagerank`, no networkx).
- Weights follow Aider's shape: distinctive snake/camel identifiers and task terms weigh more,
  common identifiers and leading-underscore names weigh less, references from a
  task-relevant path weigh 50×.
- Ranking personalizes on exact path components/stems, lifts files whose definition names
  echo the task, and orders symbols by graph rank; output respects the character budget.
- The graph inputs (definitions and top references per file) persist in
  `.miser/cache/repomap.json`, validated by `mtime_ns:size` and a version key; the cache is
  pruned to the current file set and excluded from workspace scans.
- Tests cover PageRank properties, hub-vs-isolated ranking on Python and JS fixtures,
  budget bounds, cache reuse/invalidations, corrupt cache recovery, and syntax-error files.

### Phase 3 — recursive context compaction

- `WorkingMemory` keeps a durable breadcrumb (files with versions, edited flags, errors,
  latest test status, compaction counters) apart from a small raw observation ring.
- The agent estimates the prompt each step; at 75% of the token budget it digests older
  turns (tool payloads reduced to paths/versions/status, bulky arguments truncated), drops
  all but the most recent turn, folds observations into counters, and rebuilds the prompt,
  retrying once if still over the threshold.
- Every compaction is a ledger event (`dropped_turns`, prompt estimates before/after,
  estimated tokens freed) and the receipt exposes `compactions` and
  `context_tokens_freed_estimate`; these are diagnostics, never added to provider tokens.
- A 12-step test asserts every prompt stays below 3,500 estimated tokens and that the
  breadcrumb keeps the latest file version and test status without copying source bodies.

### Phase 4 — model fallbacks and architect/editor separation

- `ModelClient` accepts a fallback chain (`MISER_FALLBACK_MODELS`, `/model primary,fallback`,
  or `--fallback-models`) and retries with the next model on HTTP 429 or 503 only. Auth and
  other errors fail immediately; the exhausted chain raises the last transport error.
  Fallbacks are surfaced to the user and recorded as `model_fallback` ledger events.
- Optional architect/editor mode (`MISER_ARCHITECT_MODEL`, `--architect-model`,
  `/architect`) makes one tool-free planning call with the reasoning model, records its
  usage and the plan, and passes the plan to the editor model that performs all edits.
  A failing architect is recorded as a failed request and the editor continues without a plan.
- Tests cover 429/503 fallback, no fallback on 401, exhausted chains, env/list config,
  architect-then-edit success, architect failure resilience, and receipt counters.

### Phase 5 — golden-task evaluation

- `python3 -m miser evaluate --demo python` runs the fixture as a golden task and grades
  each attempt against `GOLDEN_LIMITS` (≤4 model calls, <6,000 provider tokens, complete
  usage, tests passing). `report.json` stores the grade beside the receipt.
- `docs/benchmark-results.md` holds the method, the recorded attempt, and the still-empty
  before/after table. **No golden run has passed on this machine**: Bifrost was not
  listening on `localhost:8080`, so the recorded attempt stopped at `model_error` with
  unknown usage and zero provider tokens. That is a blocked live check, not a result.

## Not yet validated live

The user's shared live receipt confirms Gemini calls through Bifrost with usage
accounting; that run stopped at budget exhaustion after an edit, before verification.
The host-driven verification change addresses this flow and needs a fresh live test.
Tavily remains unvalidated live. During this work the local gateway was not listening,
so no live model, fallback, compaction-quality, or Tavily call has been validated here.
Local protocol tests cannot establish provider compatibility, fallback behaviour against a
real 429, or summary quality.

## Deferred from master plan

Resolved call/import graphs, selected test execution, mutation probes, supply-chain/CVE audits, MCP packaging, OSS baseline integration, real-repository task-suite runner, model-based claim extraction, validated verdict quality, freshness scoring, and automatic evidence invalidation. Approximate references must not be represented as a resolved graph. These are pending features, not silently completed plan items.
