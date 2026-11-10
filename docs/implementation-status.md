# Implementation status

Audit update (2026-11-09): baseline `6898ab5` reproduced at 249 tests; the audited
working tree passes 290 tests. See [audit report](audit-report.md) for fixes and
open risks. Counts and live-service statements below describe their recorded
sessions, not current gateway availability or a security guarantee.

## Charcoal and observable activity (2026-11-10)

Current full suite: **447 in 32.424s, OK**. Shared #141414 charcoal theme, neutral
surfaces and subdued cyan/blue accents replace navy. A persistent activity rail
shows actual model/tool/check/approval stages above the composer. This adds no
model calls and does not expose private thinking. Separate provider reasoning
summary streaming remains unimplemented. Actual native CLI PTY regressions and
80×24/120×36 visually inspected cell captures are documented in terminal-ui.md.

## Guarded deletion and lightweight file mode (2026-11-10)

Latest full suite: **446 tests in 25.650s, OK**, baseline 430/24.859s. New delete_file
requires a current read/version, fresh approval and retained private recovery copy.
It is excluded from parallel read-only batches. Deletion-aware diffs, live undo and
compacted-memory invalidation are covered by regressions. /files on exposes seven
bounded text tools and a shorter prompt, no automatic tests/commands/architect;
changes are edited_unverified. Default coding catalog is now 20 and required checks
remain default. /files off restores ordinary routing; /checks required restores checks
if previously manual. App-level final-syscall isolation limits remain.

Actual CLI PTY with a simulated provider passed cancel/no writes, fresh approval,
delete/create in three requests with zero tests, unverified display, undo bytes/mode
and clean exit. No live speedup or modification of user cat/config files claimed.
See [file-operation evidence, usage and limits](file-operations.md).

## Timing and explicit manual checks (2026-11-10)

Latest full suite: **430 tests in 81.431s, OK**. Chat displays selected route/check
policy, actual check-running state and host duration summaries; `/timing` repeats
latest-prompt diagnostics without model requests. Failed native tools now show their
bounded error reason. Missing UI startup prints a complete project-venv command.

`/checks manual` explicitly skips automatic tests/architect and removes run_tests;
edits finish `edited_unverified`. `/checks required` restores default verification.
No command/file guards are weakened. Real CLI PTY manual-mode verification used a
simulated provider, actual temporary file creation, zero tests and clean exit.
File deletion is still unsupported, and live speedup is not established. See
[policy details and real check outputs](terminal-ui.md).

## Native Textual application (2026-11-10)

The actual interactive CLI now selects `miser.tui.textual_app.MiserApp`, a native
Textual application. The optional `tui` extra now supplies Textual; core dependencies
remain empty. The former row-rendered Rich application remains only for legacy
compatibility tests and is not an interactive CLI route. Persistent native input,
scrollable Markdown messages, responsive sidebar, streaming, modal approvals and
real backend integration are implemented. Run `.venv/bin/python -m miser chat . --tui`.
Final verification: 417 tests in 72.571s, OK, using `.venv/bin/python`.
See [current UI verification and captures](terminal-ui.md). The Rich redesign notes
below describe the earlier implementation, superseded by this native application.

## Recent turns, rendering and local latency (2026-11-09)

UI redesign follow-up: the existing optional Rich TUI now has a compact welcome,
shared palette, charcoal user surfaces and persistent focus composer. Retained raw
Markdown response blocks support rich formatting and resize reflow. Regression
coverage fixes omitted non-streaming replies, merged model streams, lost repaint
updates, cancellation waiting, Unicode input wrapping, full-row cursor visibility,
miscolored failure status, unknown-usage labels and clipped diff tails. An actual
PTY test exercises keyboard/streaming/resize/approval/real acceptance commands with
scripted provider replies. See [UI evidence and limits](terminal-ui.md); older
statements below describe the pre-redesign checks.

- Root cause: only `answer_question` saved conversation pairs. Local file reads and
  coding/inspection tasks were absent, so a later question saw an older user turn.
  The shared task entry now records every non-slash turn in both line and TUI
  routes, including interrupted/failed turns. Agent outcomes use `agent_message`
  when available, otherwise an explicit status/file summary, never replayed tools.
- Exact previous-message queries are answered locally. Other questions and task
  loops receive the latest three bounded pairs as history/context. At most six
  pairs / 12,000 serialized UTF-8 bytes are retained; each message is capped at
  1,500 UTF-8 bytes plus an explicit truncation marker. New instances start empty;
  resume restores metrics, not a full conversation. This does not change profiles,
  command approvals or file guards. No automatic cross-session learning is claimed.
- The screenshot's four-line read wording now matches the guarded local route;
  a compound edit suffix still cannot be consumed as a file display. A single
  synthetic-file smoke measured 11.456 ms for that read and 0.057 ms for previous
  message recall, with zero model requests. These are local observations, not
  provider latency benchmarks or guaranteed timings.
- Fixed clipped code lines, a closing streamed fence printed as backticks, ANSI/
  wide-character wrapping, overlong headings/model labels, adjacent turn spacing,
  and TUI transcript cropping on resize. Scroll offsets count wrapped rows.
  Repaints reflow only a sufficient transcript suffix, not the entire session.
  Unicode handling uses codepoint/cell widths, not full emoji-grapheme shaping.
- Streaming and independent read-only parallel batches already existed and remain
  enabled. Provider-side prompt caching is not newly implemented or verified.
  Further provider latency work needs real first-token/request/retry measurements
  and documented gateway cache support; do not claim speedups from simulated calls.

## External MCP tools (2026-11-09)

- Opt-in HTTP tools-only client in `miser/mcp.py`; explicit external host config,
  read-only tool allowlists and fresh per-call approval. No subprocess server
  launches, inline credentials, auto-discovered config, retries or new dependencies.
- Adds two generic tools only when configured; selected schemas become 11/14/21.
  MCP tools never enter parallel batches. Headless discovery is allowed; calls
  require an interactive approval channel. Remote metadata/results are untrusted
  tool data. Host classification does not prove service behavior or provide an OS sandbox.
- Bounded JSON/SSE, explicit 2026-07-28 or 2025-11-25 protocol pin, legacy session
  cleanup, credential redaction and metadata-only ledger events. RPC success is
  distinct from unknown service charges. See [scope and setup](mcp.md).
- Deterministic fake-transport coverage only; no live server, Meko connection or
  model-driven MCP run verified. TUI shutdown also releases pending edit approvals.
- Readiness follow-up: catalog size budgeting now reserves omitted names (a
  regression reproduced 10,105 bytes against the 10,000-byte cap). A two-call
  agent integration test checks fresh approvals, cached discovery and sequential
  execution without constructing parallel workers. Latest full suite: 378 OK.

## Persistent project knowledge (2026-11-09)

- New `miser/knowledge.py` stores explicitly host-saved facts under ignored
  `.miser/project-knowledge.json`. `/remember [--path PATH] FACT`, `/memory`,
  `/forget ID` and CLI `memory REPO ...` work without a model. On/off persists;
  clear is explicit. This does not automatically import the development memory.md.
- At most 20 facts of 400 characters; at most 8 whole facts / 3,000 serialized
  UTF-8 bytes enter a task-start snapshot. Facts are untrusted data in user/state
  context, never system instructions. Current task/tool profile remains unchanged.
  Normal context diagnostics include these bytes; there is no extra model call or
  fabricated provider usage. General conversation can load the same bounded data.
- Linked source hashes exclude changed/missing/unsafe files. Version checks use
  bounded regular UTF-8 reads, directory-relative opens and no-follow access;
  FIFOs/symlinks are not followed or waited on. Facts are not semantic proof.
- POSIX writer locking, private file modes, atomic replacement and fsync protect
  store updates. No cross-platform or power-loss certification is claimed. Model
  tools cannot save/overwrite this host store. Credential refusal checks configured
  keys and obvious assignments, not every possible secret. Labels do not establish
  model injection resistance. Corrupt stores fail closed; --no-memory bypasses
  loading and explicit clear allows recovery.
- Deterministic coverage includes fresh instances, repository isolation, bounded
  Unicode context, stale source/symlink/FIFO behavior, concurrent host saves,
  replacement failure, corrupt/nested input, secret refusal and CLI/slash routes.

## Capability profiles and clarification (2026-11-09)

- The catalog now has 19 tools with `ask_user`. Inspect/research/coding expose
  9/12/19 schemas; the dispatcher enforces that same selected set. Read-only loops
  skip acceptance/architect calls, read actual repository evidence and cannot edit,
  execute commands or run tests. Research alone adds the existing web tools to the
  read-only profile. Coding keeps the existing verification and approval policy.
- Explicit file reads still use the earlier zero-model route. Other task profiles
  are inferred from the user request, not repository/model text. Inference is a
  heuristic; headless CLI `--profile inspect|research` enforces a host-selected
  read-only boundary. Coding still requires a fixed acceptance command.
- `ask_user` supports a bounded question and optional choices, with three prompts
  per task. A live line/TUI answer resumes the same loop. Mixed question/action
  batches are refused; no channel or a declined answer stops as `needs_input` and
  surfaces the question. Piped and batch/--exec sessions never prompt. Raw answers
  are not persisted by clarification events (later model answers can repeat them).
- Source protection and shell allowlists were not relaxed. Verification uses
  scripted models, real temporary source files, and simulated TUI key events. No
  live provider cost, latency or remote-service correctness claim follows.

## Golden-task evaluation (Phase 7)

- The evaluation harness was already in place (`miser/evaluation.py`,
  `miser evaluate --demo python|javascript`), so Phase 7 recorded real runs instead of
  adding harness code. Each run copies `examples/<lang>_bug` into an absent output
  directory, drives the real agent loop against the configured gateway, and writes
  `ledger.json` plus `report.json` with request/tool/test events,
  provider-reported tokens and wall clock.
- Three runs used the real CLI and the real gateway with complete provider usage
  (`usage_complete: true`, `failed_model_requests: 0`, no compactions, no fallbacks):

  | Run | Status | Model calls | Provider tokens | Wall clock | Golden |
  | --- | --- | --- | --- | --- | --- |
  | `runs/golden-python-20261109a` (default budget) | `budget_exhausted` | 4 | 11,098 | 46.1 s | fail |
  | `runs/golden-python-20261109b` (40k budget) | `tests_passed` | 5 | 15,000 | 41.3 s | fail |
  | `runs/golden-js-20261109a` (40k budget) | `tests_passed` | 5 | 14,937 | 41.8 s | fail |

  Python and JavaScript both solved with one model edit and five calls, 63 tokens
  apart. The default-budget run spent all four calls on orientation (`find_files`, two
  `zoom` reads, `write_todos`) and ended before any edit.
- The measured finding is that the fixed golden limits (`max_model_calls: 4`,
  `max_provider_tokens: 6,000`) were not reached in these measured runs, so
  `golden_tasks_passed: 0` and `miser evaluate` exits 1 even on solved tasks. That is
  the grader working correctly, not a harness defect: a 15,000-token solve is not a
  golden pass under a 6,000-token ceiling.
- `request_component_tokens_estimate` in the receipt is **cumulative across requests**,
  not per request. Per call the local estimate is roughly 663 instructions + 1,696 tool
  definitions + ~420–450 state + history (410 growing to ~700), about 2,800 tokens of
  fixed overhead. Observed provider prompts were 2.4–3.4k per call, so a 6,000-token
  ceiling allows about two calls. Tool definitions are the largest fixed block.
- Coverage gap: only the bug-edit fixture is recorded in both languages. The add-test,
  cross-file refactor and lint-fix tasks from the roadmap are not run yet, so the table
  does not measure them. 249 tests still pass — this phase changed docs and added
  recorded runs, not source behavior. Full numbers and caveats live in
  [`docs/benchmark-results.md`](benchmark-results.md).

## Parallel read-only tools and tighter compaction (Phase 6)

- Independent read-only calls in one assistant turn now run on a small thread pool
  (`miser/agent.py: run_parallel_batch`, at most 8 workers). A turn is batched only
  when every call parsed, at least two calls were made, and every tool is in
  `READ_ONLY_TOOLS` (`repo_map`, `list_files`, `find_files`, `search`, `zoom`,
  `recall`, `read_many`, `blast_radius`, `web_search`, `fetch_url`). Anything else —
  edits, `run_tests`, `run_command`, `verify_claim`, `write_todos`, malformed
  arguments — keeps the sequential path, so no write ever races another write.
- Ordering is preserved: starts are emitted on the calling thread in model order,
  completions arrive through `as_completed`, activity results are buffered into model order, and tool messages, memory
  observations and the early-exit test check are emitted zipped back into model call
  order. A `tool_batch` ledger event records the tools and whether the batch ran in
  parallel; `receipt()` sums only known event kinds, so it is unaffected.
- Shared state is now lock-guarded: `Ledger` uses an `RLock` around `record`/`flush`/
  `finish`, and `WebAccess._reserve` is atomic under a `Lock`, so a parallel batch
  cannot double-spend the web budget or interleave ledger writes.
- Compaction is structured rather than a blind truncation. Each older tool result is
  replaced by a bounded digest (`compact_digest`, 600 chars) that keeps scalars,
  paths, versions, error text and pass/fail flags while trimming long text to 200
  characters. It is a local digest: no extra model call is spent summarizing.
- The last six assistant decisions (300 chars each) are kept in a `deque` and
  re-injected as `state["earlier_decisions"]`, but only after a real compaction has
  happened, so short sessions pay nothing for it.
- The compaction threshold is adaptive: normally `token_budget * COMPACTION_RATIO`,
  but lowered to `token_budget * min(COMPACTION_RATIO, 0.55)` once a single tool
  output exceeded 12% of the budget. Compaction still only fires when the estimate
  actually exceeds the threshold and always reports the tokens it freed.
- Local verification: 249 tests pass (`python3 -m unittest discover -s tests -q`),
  including 7 new cases in `tests/test_agent.py` and a 12-thread budget race in
  `tests/test_web.py`. Coverage includes a parallel batch, a mixed batch falling back
  to sequential, ordered results, both threshold branches, digest bounding and
  unparseable output, and decision re-injection after compaction.
- Wall clock, measured on this host with real tool calls over 8 source files
  (`/tmp/miser_batch_bench.py`, medians of 7 runs):

  | calls | sequential | parallel |
  | --- | --- | --- |
  | 1 | 0.5 ms | 0.4 ms |
  | 2 | 0.9 ms | 1.5 ms |
  | 4 | 2.3 ms | 3.6 ms |
  | 8 | 6.6 ms | 10.3 ms |

  Local file reads are already sub-millisecond, so thread setup costs more than it
  saves and parallel batching is *slower* there (≈0.6×). Its value is network-bound
  tools: with a **simulated** 150 ms per call (no real network used), 4 calls took
  601 ms sequentially vs 151 ms in parallel, ≈4.0×. So the acceptance sentence "wall
  clock drops measurably" holds only for `web_search`/`fetch_url`; for local reads it
  is a few milliseconds of regression inside a multi-second model turn. Outputs were
  asserted byte-identical to the sequential path for all 8 files.

## Final-answer status update

- A text reply that ends the turn with no tool call now finishes as `answered`
  instead of `incomplete`. Chat and research tasks legitimately need no edit, and the
  old label ("no more tool calls", yellow warning) made a correct answer look like a
  stalled run. An empty reply still finishes as `incomplete`, and a reply cut off at
  the output cap still finishes as `truncated`.
- `answered` renders with the neutral info glyph in `miser/ui/render.py`; the result
  panel reads "answered". It is never treated as passing tests — acceptance remains
  only `tests_passed`.
- Live check: `runs/session-764157a062c5` (7 model requests, 7 tool calls, 17,808
  provider tokens, no files modified) ended `status: "answered"` with the answer text
  in `agent_message` and an empty `patch.diff`.
- Local verification: 241 tests passed, including a new empty-reply case in
  `tests/test_agent.py`.

## Knowledge and web update (Phase 5)

- Two new tools, `web_search` (Tavily) and `fetch_url`, live in `miser/web.py`
  (`WebAccess`). They make MISER 18 tools.
- Fetched text is always labelled untrusted and returned as a `tool` message; it is
  never placed in the system prompt. The system prompt states that page content is
  data, and that instructions found inside it must not change tool selection.
- `check_url` requires `https`, except plain `http` for a loopback test double.
  URLs with embedded credentials are refused, as are non-http(s) schemes.
  Loopback, private, link-local, multicast and reserved hosts are refused unless
  `MISER_WEB_ALLOW_PRIVATE=1` is set for deliberate local testing. Hostnames are
  checked literally, so this is a policy guard, not a DNS-rebinding-proof sandbox.
- Redirects are disabled at the transport layer and each hop is re-validated before
  it is followed (at most 3 hops). Bodies are capped at 500,000 bytes and the text
  handed to the model at 8,000 characters; non-text content types are refused.
  HTML is reduced to readable text by a stdlib `HTMLParser` that skips
  `script`/`style`.
- Search and fetch share a per-run budget of 8 calls and record `web` ledger events;
  the receipt exposes `web_calls`.
- Local verification: 240 tests passed, including 18 new cases in
  `tests/test_web.py` (URL policy, redirect re-validation, truncation, untrusted
  labelling, budget, and tool wiring). The fetch tests substitute the transport
  because the host cannot bind sockets, and are labelled simulated.
- Live check (host script, real services, not model-driven): a real Tavily search
  returned 3 results, and two real fetches returned HTTP 200 `text/html`
  (`docs.python.org/3/library/pathlib.html`, `realpython.com/python-pathlib`),
  reduced to text and capped at 8,000 characters. The Real Python fetch also had to
  follow a live redirect, so redirect re-validation is confirmed against a real
  server. One Stack Overflow result returned HTTP 403 (site bot protection); the tool
  surfaced the error rather than retrying or bypassing it.
- Live model-driven check: `runs/session-e4d476853be7` asked for the exact signature
  and version-added note of `Path.read_text` from
  `https://docs.python.org/3/library/pathlib.html`, with instructions not to answer
  from memory. It used 4 model requests and 4 tool calls for 18,777 provider tokens,
  and the recorded answer was reported to cite the fetched URL. This is evidence
  of retrieval, not answer correctness: the earlier claim that `read_text` gained
  `newline` in 3.10 is contradicted by this host's Python 3.12.3 signature, which
  has only `encoding` and `errors`. No semantic correctness claim is established.
- Still pending: proving that a model ignores injected instructions. Existing unit
  tests assert untrusted labels and returned text, not model behavior. This host
  cannot bind local listeners; simulated transport tests require no listener.

## Planning and progress update (Phase 4)

- New 16th tool `write_todos`, backed by `miser/todos.py` (`TodoList`). The model
  rewrites the whole ordered list on each call; the runner rejects a call whose
  arguments are not exactly `{"todos"}`, and the list is validated before it
  replaces the previous one, so a bad update leaves the old plan intact.
- Limits: at most 20 items, 200 characters per task, with `{task, completed}`
  fields; there is no `in_progress` state. Each accepted update bumps a `revision`.
- The plan is re-injected into every prompt as `state["todos"]`, so it is in context
  even when the model does not repeat it. If a turn did tool work without
  re-emitting the list, the host attaches a `plan_reminder` and increments
  `stale_checks` — skipped on the final step, since there is nothing left to do
  with the nudge.
- The terminal and TUI each render one compact checklist after a successful
  `write_todos` result (`✔`/`○`), so the transcript shows an update per step rather
  than a single dump.
- Local verification: 222 tests passed, including 14 new cases in
  `tests/test_todos.py`. No live model requests were made for this update, so the
  acceptance sentence is proven by unit tests over the runner, loop and renderer,
  not by a model-driven task.

## Supervised execution update (Phase 3)

- New 15th tool `run_command` with `action = run | status | stop`. It takes an `argv`
  array, never a command string, and is spawned with `shell=False`; no code path
  reaches a shell.
- Binaries come from an allowlist of prefix rules: `python3 -m unittest`,
  `python3 -m pytest`, `python3 -m mypy`, `pytest`, `ruff`, `mypy`, `node --test`,
  `git status`, `git diff`. Anything else is refused with a clear message.
- Any shell metacharacter in any argument (`; & | < > $ ` \n \r ( )`) is refused
  before execution.
- Each invocation needs fresh approval: yes or no. The earlier exact-argv "always"
  cache was removed during the audit. The child process gets only a small allowlisted
  environment; gateway/search credential variables are not forwarded. Repository
  code can still read credentials from disk: this is not an OS sandbox.
- stdout, stderr and the real exit status are returned unchanged; a non-zero exit is
  a result, not an exception.
- `background=true` starts a job with a log file under `.miser/jobs/`; `action=status`
  reports running/exit status and output, and `action=stop` kills the process group.
- Because approval is a real channel, the headless path (`python3 -m miser run`) has
  none and therefore **refuses** `run_command`. This is intentional; only the
  interactive terminal and TUI prompt.
- Local verification at that time: 208 tests passed, including 8 new cases in
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

- `Workspace.edit_batch` applies 1–10 exact replacements across files: every snapshot,
  version, and match is validated and contents/backups staged before replacement.
  Replacement is atomic per file; multi-file rollback is best effort and incomplete
  rollback is explicitly reported with retained backup paths. No crash-atomic claim.
- `Workspace.apply_unified_diff` parses standard git-style hunks (counts validated,
  `/dev/null` creation/deletion refused, `\ No newline at end of file` honoured), verifies
  each hunk against the read snapshot, and uses the same staged replacement path.
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
  unknown usage and zero known recorded tokens. That does not prove zero remote
  spending; it is a blocked live check, not a successful result.

## Live evidence and remaining gaps

The earlier gateway-unavailable notes are historical. The audit found the recorded
smoke solve (8,948 tokens), three golden attempts, and a web session (18,777 tokens,
3 web calls, legacy `incomplete` status) on disk. No new live calls were made in
the audit. Gateway availability, model injection resistance, fallback behavior
against real remote failures, compaction quality and comparative efficiency are
not established by the deterministic suite.

## Deferred from master plan

Resolved call/import graphs, selected test execution, mutation probes, supply-chain/CVE audits, MCP packaging, OSS baseline integration, real-repository task-suite runner, model-based claim extraction, validated verdict quality, freshness scoring, and automatic evidence invalidation. Approximate references must not be represented as a resolved graph. These are pending features, not silently completed plan items.
