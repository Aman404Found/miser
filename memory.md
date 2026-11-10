# MISER — working memory

Living log of what has been done, what is verified, and what is next.
Update this file at the end of every work session. Newest entries at the top of
"Session log"; keep "Current state" accurate rather than appending forever.

Last updated: 2026-11-10 (current-state consolidation and actionable handover)

---

## Hard constraints (do not violate)

- Product name is **MISER**, never NISER.
- `opencode/` and `aider/` are reference repos only: never modify, test, or package them.
- **No model-controlled arbitrary shell execution.** Acceptance commands are explicit
  and host-controlled.
- Keep path protections, symlink checks, exact-edit version checks. Treat repository
  content as untrusted.
- Never print `.env` values or `TAVILY_API_KEY`.
- Never claim success unless the required verification actually passed. Distinguish
  provider-reported usage from local estimates. Never fabricate benchmarks or results.
- App-level guards are not an OS sandbox — say so when relevant.
- Verify in order: baseline tests → regression tests → focused run → full suite.
  Label simulated vs real.

---

## Current state

- Python 3.12.3, `requires-python >=3.11`, no required runtime dependencies for
  the core CLI. Optional `tui` now supplies Textual >=8.2.8,<9; `ui-test` adds pyte
  only for development. Prepared `.venv` has Textual 8.2.8, Rich 15.0.0, pyte 0.8.2.
- **Tests: 430 passing** — latest full suite, exit 0, 81.431s. This increment
  reproduced 417 in 89.225s before changes, then added ten latency/policy tests and
  three native UI regressions. Native rebuild previously passed 417 in 72.571s;
  its baseline was 399 in 21.118s. Earlier counts: baseline 249 at `6898ab5`, audit 290,
  local reads/branding 299, profiles/questions 317, knowledge 337, MCP 360,
  context/layout 376, MCP readiness 378, earlier Rich redesign 399. Native rebuild
  adds 16 widget/backend regressions, one actual CLI PTY regression and one
  deterministic process-cleanup probe regression. Run the full
  suite with `.venv/bin/python` and optional UI/test extras installed.
- **Tool catalog: 19** — `repo_map`, `list_files`, `find_files`, `search`, `zoom`, `recall`,
  `read_many`, `write_file`, `edit`, `edit_batch`, `apply_patch`, `blast_radius`,
  `run_tests`, `verify_claim`, `run_command`, `write_todos`, `web_search`, `fetch_url`, `ask_user`.
- **Local file-display route:** explicit requests such as `read Readme.md file and
  print first line` bypass the model, acceptance tests and shell in both line/TUI
  task entry points. Paths still use Workspace guards; case fallback is unique-only,
  reads are bounded and a local receipt is written. This host action is separate
  from the model tool catalog. Compound requests use the appropriate task profile.
- **Branding:** MISER uses compact plain-text branding and an assistant diamond;
  the giant block-font welcome banner has been replaced by the persistent session
  layout. Historical M/N confusion motivated the earlier glyph fix. Name unchanged.
- **Recent-turn context:** one shared line/TUI task entry records every submitted
  non-slash turn, including local reads, greetings, agent tasks and failures. The
  original bug stored only general-question pairs, skipping intervening file reads.
  Exact previous-message queries now return the latest user turn locally. Other
  model requests receive the latest three pairs; no past tools are replayed. Store
  bounds: six pairs / 12,000 serialized UTF-8 bytes; 1,500 UTF-8 bytes per message
  plus explicit truncation marker. History is live-session only; --resume restores
  metrics, not full conversation. Project facts remain a separate feature.
- **Native UI:** the actual CLI now selects `miser.tui.textual_app.MiserApp`.
  Launch `.venv/bin/python -m miser chat . --tui`. It uses Textual native layout,
  Markdown, scrolling, editor and modal approvals. Header/footer/composer persist;
  sidebar hides below 118 columns. Streaming replaces a single native widget per
  request. Original sources/patches remain separate from display sanitization.
  Links are inspected as data, never opened automatically. Diffs are collapsible
  with patch-line numbering, unified hunk coordinates and change counts. Legacy
  Rich row UI remains for old tests, not a CLI launch route. `--no-tui` and
  noninteractive commands retain the line interface; forced --tui fails clearly
  when unavailable. Prompt history is bounded private JSON with multiline support.
- **UI verification:** actual CLI PTY with simulated provider covers 80×24,
  120×36, 160×45, Markdown streaming, scrolling, multiline draft, real failing tests,
  Ctrl+C refusal/no write, fresh approved edit, real passing tests, receipts and
  clean exit. Separate unmodified CLI PTY exercises hello/local read/error/exit
  without provider mocks or model/test events. Native headless tests cover fresh
  command/MCP approval callbacks, ask_user, approve-all edits and re-enabling prompts,
  unknown usage, literal diff paths, history and host-restricted wakeups.
  See docs/terminal-ui.md and docs/ui/native-*.png. Provider outputs in the coding
  workflow are simulated; no successful live gateway run or latency gain verified.
- **Restricted-host compatibility:** socketpair send fails EPERM here, preventing
  asyncio cross-thread wakeups/executor shutdown. A capability-gated public-loop
  polling timer handles only EPERM/EACCES; normal hosts retain native wakeups.
  No listener is bound. This does not change execution policy or create a sandbox.
- **Capability profiles:** coding exposes all 19 tools by default and retains required-policy acceptance
  verification/command approval (manual policy omits run_tests); inspect exposes 9 local read/clarification tools;
  research exposes 12, adding existing web/evidence tools. Read-only loops inspect
  real source, skip baseline tests and architect calls, and reject edits, tests and
  commands at dispatch. The language router is heuristic; `run --profile inspect`
  or `research` gives an explicit host-selected boundary. CLI run coding still
  requires --test-command; interactive manual checks can operate without one. Model/repository content cannot change the selected profile.
- **Task clarification:** ask_user pauses a live line/TUI loop for numbered choices
  or free text, then resumes with the user answer. Three questions maximum; mixed
  question/action batches are refused. No channel or a declined answer finishes
  needs_input and displays the question. Piped/batch/--exec sessions never prompt.
  Clarification ledger events omit raw answers; later model messages may repeat them.
- **Persistent project knowledge:** /remember [--path PATH] FACT saves a host fact;
  /memory reviews/toggles/clears it; /forget ID removes it. CLI memory REPO ...
  equivalents need no model. Up to 20 facts, 400 characters each; up to 8 whole
  facts / 3,000 serialized UTF-8 bytes enter each task-start context, ranked by
  keyword overlap and recency. General conversation can load this data too.
  Optional source hashes exclude changed/missing/unsafe source entries from context
  while keeping them reviewable. Facts are untrusted data, never system instructions.
  Model tools cannot save or overwrite the private store; no automatic learning.
  The local ignored .miser/project-knowledge.json store uses POSIX no-follow access,
  locking, private files, atomic replacement and fsync. No cloud sync or verified
  Windows support. chat/run --no-memory bypasses loading, including invalid files;
  corrupt stores otherwise fail closed. Knowledge does not add a model tool (19
  remain), and MISER does not automatically load this development log memory.md.
- **External tools:** opt-in HTTP MCP read-only subset; explicit external config,
  host allowlists and fresh per-call approval. Two generic tools are added only
  with configuration (11/14/21 schemas); default catalog remains 19. CLI mcp and
  /mcp provide discovery without a model. Headless calls refuse; MCP tools never
  enter parallel batches. No stdio/process servers, retries or auto-discovered
  config. Remote content is untrusted; host classification is not an OS sandbox
  or proof of remote behavior. Protocol pins: 2026-07-28 default, explicit legacy
  2025-11-25. See docs/mcp.md for scope, setup, accounting and limits. No live MCP
  server, Meko connection or model-driven MCP run has been verified.
- **Timing/host verification policy:** every chat route is visible with its check
  policy. `/timing` reports latest-prompt wall/model/test/other-tool sums; parallel
  and nested work can overlap, so sums are not a wall-time partition. Model waits
  include client retries; failed request durations and missing/cancelled durations
  are explicit. New task_timing events do not alter receipt billing/count fields.
  Greetings/questions do not reuse previous ledgers; their timings remain session-local.
- **Why tests run:** required (default) coding runs baseline and post-edit acceptance
  checks. Baseline failure is context, not a requirement to proceed. Local reads,
  recall, greetings, general questions and inspect/research skip acceptance tests.
  `/checks manual` is a new explicit session-local host choice: no automatic tests,
  no run_tests schema/dispatch and no optional architect; actual guarded edits end
  edited_unverified after a final reply. `/checks required` restores the default.
  `/run` or freshly approved commands remain explicit host test actions. Manual
  mode can leave code unverified; it is not an automatic text-only exemption.
  Path/version/sensitive/test-file/approval/command protections remain active.
- **Observed slow run:** inspected runs/session-d1203faa7bd1/ledger.json without
  printing file content/secrets. It reports budget_exhausted, baseline 55.635s,
  six model events totalling 71.533s and failed apply_patch/run_command calls. The
  supplied screenshot shows 429 retry. Ledger events omit exact tool errors/args,
  so their precise causes are not established. Source confirms file deletion is
  unsupported: apply_patch accepts existing-file edits only. UI now displays bounded
  actual tool errors and instructions forbid trying alternate shell deletion.
- **Next work:** a guarded, version-checked deletion operation with fresh approval,
  diff and undo tests; a smaller file-task capability set; smarter host verification
  selection/cache with complete invalidation. None is implemented yet. DNS/filesystem
  isolation, compaction and durability issues remain open. Browser/UI verification
  and budgeted delegated workers remain pending. No successful live speedup measured.
- `docs/agent-roadmap.md` Phases 1–7 are implemented and covered by tests.
  Phase 5 was exercised against the real services by a host script: a real Tavily
  search returned 3 results and two real page fetches returned HTTP 200 (one of them
  followed a live redirect). A model-driven fetch task is now recorded too
  (`runs/session-e4d476853be7`, 18,777 tokens, 3 web calls, legacy `incomplete` status).
  Its former "correct version notes" claim was too strong: the 3.10 newline claim
  conflicts with the host's Python 3.12.3 `Path.read_text` API.
  Unit tests assert untrusted labels and transport, not model resistance to
  injected instructions. Model behavior remains unverified; local socket listeners
  cannot run on this host.
- **Phase 6 is in.** Independent read-only tool calls in one step run on a worker
  pool (`MAX_PARALLEL_TOOLS=8`); the audit now buffers activity into model order; `run_tests`,
  `write_todos`, edits, `run_command` and `verify_claim` stay sequential. Compaction
  keeps a structured digest per tool result plus a bounded `decisions` deque that is
  re-injected only after a real compaction; the threshold drops from 75% to 55% when
  one tool output exceeds 12% of the budget. `Ledger` uses an `RLock` and the web
  search budget a `Lock` so parallel tools cannot race counters. Honest measurement:
  real local reads are slightly *slower* in parallel (thread start-up dominates);
  simulated 150 ms network calls were ~4× faster (601 ms → 151 ms for four). Outputs
  were identical either way.
- **Phase 7 is in (recorded runs, thresholds not met).** Using the existing
  `miser evaluate` harness, three real runs were recorded: default budget ended
  `budget_exhausted` (4 calls, 11,098 tokens, no edit); with a 40k budget Python and
  JavaScript both ended `tests_passed` (5 calls; 15,000 and 14,937 tokens). All three
  fail the fixed `GOLDEN_LIMITS` (4 calls / 6,000 tokens), so `golden_tasks_passed: 0`
  and the CLI exits 1 — correct grader behavior, not a harness bug. Per-call fixed
  overhead is ≈2,800 estimated tokens (663 instructions + 1,696 tool definitions), and
  the receipt's component block is cumulative, not per request.
- A text-only final reply finishes as `answered` (neutral info glyph), not
  `incomplete`; an empty reply stays `incomplete` and an output-capped reply stays
  `truncated`. Live confirmation: `runs/session-764157a062c5`.
- Phase 3 supervised execution exists (`miser/execution.py`), but the headless
  `python3 -m miser run` path has no approval channel, so `run_command` refuses there
  by design. Interactive `miser` and the TUI prompt per invocation.

### Environment notes

- **Git works again.** The repo was re-initialised on 2026-11-09 and the Phase 1–2
  snapshot committed as `04f4b8b` (61 files; no reference repos, no secrets, no
  `runs/`). `.gitignore` covers `opencode/`, `aider/`, `.agents/`, `.aws/`, `.codex/`,
  `.freebuff/`, `runs/`, `.miser/`, caches, and `.env*` except `.env.example`.
- **Gateway**: Bifrost is alive and authenticated. A real completion succeeded on
  2026-11-09 (`MISER_MODEL=gemini/gemini-3.5-flash`, served as `gemini-3.6-flash`,
  usage reported 7 prompt / 13 completion / 20 total tokens). A tool-enabled request
  on that route returned **HTTP 429** after 3 attempts, but the limit is
  route-specific, not account-wide: `gemini/gemini-3.5-flash-lite` returned a valid
  tool call (`finish_reason: "tool_calls"`, 58 tokens). `gemini/gemini-2.5-flash-lite`
  returned **HTTP 404** even though `/models` lists it. Use
  `gemini/gemini-3.5-flash-lite` for live work.
- **Reasoning-token budget risk**: the successful short request returned empty
  `content` because all 13 completion tokens were `reasoning_tokens`. The agent caps
  output at `min(1500, remaining - estimated_input)` (floor 256), so a reasoning
  model can spend the whole cap thinking and emit neither text nor tool calls. Now
  handled: a `finish_reason == "length"` reply with no tool calls finishes as
  `truncated`, not `incomplete`.
- **Real smoke run exists**: `runs/smoke-phase12-20261109` ended `tests_passed`
  (4 model calls, 6 tool calls, 8,663 in / 285 out / 8,948 total provider tokens,
  0 failed requests, 0 compactions). This is one task, not a benchmark.

---

## Session log

### 2026-11-10 — Consolidated current memory and next-agent handover

- User requested up-to-date memory plus explicit next work. Re-read both documents,
  checked git HEAD/status, and replaced the old historical Next steps/commands with
  the actual queue. HEAD remains 6898ab5; substantial later work is uncommitted.
- Rewrote HANDOVER_PROMPT.md around the current Textual app, interpreter mismatch,
  timing diagnostics, explicit manual/required checks and unresolved delete/create
  request. Removed stale flagship-console descriptions and old implementation plans
  that could trigger redoing completed phases or mislabel live evaluation as synthetic.
- Defined next deletion increment: checked prior read/version, fresh approval, no
  rm, honest failure behavior, accurate diffs, safe undo/metadata and temporary-fixture
  coverage. Follow with smaller file-task capability sets and verification selection;
  carry DNS/filesystem safety, compaction/durability, live MCP and benchmark gaps.
- Preserved latest observed 430/81.431s OK as a historical check, not a fresh run.
  This session changes only memory.md and HANDOVER_PROMPT.md; no implementation or
  test changes. git diff --check passed for both documents; reference/example
  diff exclusion was empty. No new full-suite run or live-provider check claimed.


### 2026-11-10 — Routing/timing visibility and explicit manual verification

- Baseline full suite: `set -o pipefail; .venv/bin/python -m unittest discover -s
  tests -q`: 417 in 89.225s OK. New regression checks failed before implementation
  (missing diagnostics/failed-request durations/manual checks/tool-error visibility).
- Added host route/policy activity, baseline/test-running states, timing summary
  and /timing. Model requests include retry waits, tests are not double-counted via
  run_tests tool wrapper, parallel tool sums are labelled overlapping, missing
  durations/unfinished requests are explicit. Current ledger only is used. Receipt
  counters, schema fields, provider usage and evaluation budgets remain unchanged.
- User's screenshot showed system python launching line fallback. Verified system
  Python lacks Textual, project .venv has Textual 8.2.8. Startup now prints a complete
  .venv launch command; README documents activation to keep python3 invocation.
  No automatic environment execution or system-wide package installation added.
- Inspected the user's slow run: 55.635s acceptance baseline, 71.533s across six
  model events, budget_exhausted. Failed tool events retain no error message, so
  exact arguments/errors cannot be inferred. File deletion is independently proven
  unsupported by source. User cat.txt/config.json were not read or modified.
- Added /checks manual|required, required by default each session. Manual avoids
  automatic baseline/post-edit tests and optional architect, omits/rejects run_tests,
  and records edited_unverified after edited tasks. /status shows policy; new UI
  distinguishes skipped checks and baseline passes from post-edit success. Existing
  shell allowlists, invocation approvals, file/test/version guards are unchanged.
  Manual is explicit and can leave code unverified; not an OS sandbox. Evaluation
  defaults and GOLDEN_LIMITS were not changed. No deletion tool or rm permission added.
- Broad focused integration (latency, terminal, capabilities, agent, UI, isolation,
  local reads, history, execution, native widget/actual CLI PTY): 166 in 79.541s OK.
  Final targeted diagnostics/native selections: 16 in 1.149s OK. The earlier focused
  run caught extra diagnostics on refused ambiguous reads; preserved the existing
  no-output assertion by delaying local route output until guards pass.
- Actual native CLI manual-policy PTY at 120×36, provider explicitly simulated:
  real temporary essay file created, zero tests, two simulated model events,
  edited_unverified result/timings visible, clean exit. Scratch script:
  /tmp/miser-manual-pty.py. No live provider calls or speedup benchmark performed.
- Final full suite: 430 tests in 81.431s OK. Core -S help, diff --check and empty
  reference/example diff checks passed. Updated UI guide/README/status/roadmap/handover
  and this memory. No commits/pushes, secrets printed, reference edits or new deps.


### 2026-11-10 — User asks what remains and why answering waits for tests

- Re-read Terminal._task, task_profile, run_agent baseline/post-edit paths, current
  roadmap and open audit findings. Confirmed tests are not universal: local and
  read-only routes skip them. Coding always runs baseline (does not require it to
  pass), and post-edit verification may rerun the configured full suite. Even a
  simple new text file uses that coding path today. Model inference/retries are
  separate latency sources; no fresh wall-clock/provider speed benchmark was run.
- Recommended next latency increment: visible routing/timing diagnostics and better
  read-only classification, followed by an explicit host verification policy for
  task types. A reusable baseline would require host-controlled invalidation of
  workspace/test/config/environment inputs and must not silently claim verification
  for changed or unknown state. This is proposed, not implemented or measured.
- Remaining: DNS-pinned network transport and descriptor-relative filesystem safety
  (app guards are not an OS sandbox), compaction of read_many results and power-loss
  ledger durability, successful live gateway/MCP verification, broader evaluation
  fixtures and unmet golden limits, optional browser verification/delegated workers,
  and full conversation resume (currently metrics only, with bounded live history).
  HTTP MCP read-only tools already exist; live interoperability is unverified.
- Ran `PYTHONPATH=tests .venv/bin/python -m unittest test_capabilities test_local_reads
  test_recent_turns -q`: 43 tests in 0.537s, OK. Scripted-provider tests verify routing
  without live requests. Latest full suite remains the previous 417 in 72.571s OK;
  not rerun for this documentation-only update. No runtime code changed.


### 2026-11-10 — Native Textual application replaces interactive row renderer

- User explicitly requested proper framework architecture; selected optional
  Textual, kept core deps empty. Installed verified official wheels in ignored
  project .venv, leaving system Python unchanged. No reference repo touched.
- CLI now launches native MiserApp; forced --tui prevents silently starting the
  wrong interface. Existing Terminal backend remains authoritative for models,
  tools, approvals, budgets and accounting. Dedicated backend thread posts typed
  messages; presentation adds no model requests. Legacy UI tests remain historical.
- Added native composer, conversation/semantic activity cards, sidebar, Markdown,
  link inspection, collapsible diffs, edit/command/MCP/question modals, cancellation,
  scroll anchoring and guarded multiline JSON history. Explicit approve-all only
  applies to edits and respects /confirm on. Diff paths escape markup literally.
- Proven accounting defect: failed informational requests left unknown usage at
  zero. Regression fails before fix; now marks unknown without counting a completed
  provider request. Existing safety/ledger regression suite remains green.
- Actual CLI PTY test has a simulated provider plus trap forbidding live calls;
  actual version-checked edits and unittest checks fail then pass. An earlier test
  patched the wrong factory and attempted the unavailable local gateway; corrected
  before final verification. Separately exercised the unmodified production CLI
  local routes with zero model/test events, no provider patch.
- Native tests: 16 in 35.099s OK. Actual CLI PTY final targeted run: 1 in 7.570s OK.
  Existing focused integration: 202 in 12.877s OK. Final audit/native-PTY focus:
  43 in 11.612s OK. Final full suite: 417 in 72.571s OK. An initial full run
  passed 416 in 47.585s; later reruns exposed a /proc test race (416/79.736s,
  one error) and a premature PTY paint assertion (417/64.611s, one failure).
  The cleanup probe now treats only disappearing processes as gone, asserts live
  processes remain live and propagates permission errors. Added deterministic
  coverage; no assertion skipped. Approval capture now waits for patch/controls.
  Resize snapshots now wait for footer at the new bottom, not a fixed sleep.
- Visually inspected actual decoded CLI PTY cell captures at 80×24, 120×36 and
  160×45 plus 80×24 approval and completed-task receipt. PNGs explicitly label
  simulated provider; not fabricated mockups, OS screenshots or live-model evidence.
- Updated README, terminal-ui guide, status, roadmap and handover. Core -S help,
  native chat help, diff whitespace check and reference/example diff exclusion pass.
  No commits/pushes, secrets printed, budget/benchmark changes or user cat.txt/config.json
  changes. Socket listeners, successful live provider behavior and universal emoji/
  other-OS rendering remain unverified. Cooperative cancellation may wait on HTTP.


### 2026-11-10 — UI handoff completed

- Re-ran `set -o pipefail; python3 -m unittest discover -s tests -q` on the current
  working tree: 399 tests in 19.756s, OK, including the actual PTY integration test.
  No runtime code was changed during this follow-up. Suite duration is not an
  agent/provider latency benchmark.
- Restored explicit keyboard, approval and non-interactive selection documentation
  in docs/terminal-ui.md, preserving useful operational guidance from the old guide
  alongside the redesign and actual captured-frame evidence. The older banner,
  unhighlighted-Markdown and simulated-only layout descriptions were superseded.
- Updated this memory file. Existing unrelated untracked cat.txt/config.json were
  left untouched. No new dependency, reference-repository edit, commit or push.

### 2026-11-09 — Terminal reference redesign and actual PTY iteration

- Baseline: `set -o pipefail; python3 -m unittest discover -s tests -q`:
  378 tests in 13.264s, OK. Captured the old actual PTY at 100x30: welcome, greeting
  and Ctrl-D exit, status 0. Reviewed small relevant sections of local nested
  OpenCode session-frame and Aider mdstream sources, read-only. No upstream code
  was copied substantially, modified, tested or packaged.
- Kept the existing Rich/layout/input architecture and optional dependency; no
  required or optional dependency declarations changed. Tested Python 3.12.3 and
  Rich 13.7.1. Shared parser adapter uses Rich when available; core still imports
  without site packages. Full Markdown is not claimed for the stdlib fallback.
- Added tests/test_ui_redesign.py with 20 regressions for rich Markdown, narrow
  tables, long diffs, fence lengths, source-preserving reflow, stable streaming,
  distinct model turns, non-streaming answers, shared layout/surfaces, honest
  status/usage, Unicode input, cursor visibility, cancellation and repaint races.
  Tests reproduced each behavioral defect before its fix. Existing giant-logo/
  92-cell layout assertions were updated to exact compact-layout assertions in
  response to the user's explicit redesign requirements; no tests were skipped.
- Added tests/test_tui_pty.py: actual POSIX PTY subprocess running Terminal/TuiApp.
  Greeting and ordinary question, streaming Markdown, resize at 60/80/140 columns,
  invalid budget error, Ctrl-C during edit approval (file remains absent), then a
  fresh approved write, actual unittest baseline/post-edit checks, real ledger
  event counts and clean terminal restoration on Ctrl-D. Provider responses and
  12-token usage per reply are simulated; no network/gateway/listener was used.
- An intermediate full run failed (398 tests, 17.417s): the PTY saw a partial
  response but never its final link. A deterministic regression proved draw()
  cleared a dirty flag set by a concurrent worker. Clearing before the snapshot
  fixes the lost repaint without extending timeouts or weakening assertions.
  Edit approval separately now observes cancellation without another key wakeup.
- Final regressions: `python3 -m unittest discover -s tests -p test_ui_redesign.py
  -q`: 20 tests in 0.165s, OK. Actual PTY with capture:
  `MISER_UI_CAPTURE=/tmp/miser-ui-after.ansi python3 -m unittest discover -s tests
  -p test_tui_pty.py -q`: 1 test in 2.378s, OK. Focused:
  `PYTHONPATH=tests python3 -m unittest test_ui_redesign test_tui_pty test_ui
  test_tui_screen test_tui_app test_recent_turns test_terminal test_agent
  test_session_isolation test_mcp -q`: 177 tests in 8.925s, OK. Full:
  `set -o pipefail; python3 -m unittest discover -s tests -q`:
  399 tests in 11.318s, OK.
- `python3 -S -m miser --help` and `git diff --check` passed. Tracked diff for
  opencode/, aider/, examples/ and pyproject.toml was empty. No commit/push.
  The pre-existing untracked root config.json was not read or modified.
- Rasterized and visually inspected actual ANSI frames at 140x32 in
  docs/ui/pty-markdown.png and docs/ui/pty-session.png, explicitly labeled real PTY
  / simulated provider. These are captured terminal output, not fabricated live
  screenshots or benchmark evidence. Font rasterization may differ from the user's
  terminal. Fixture color mode is explicit; product NO_COLOR behavior remains.
- Updated README, implementation status, handover and docs/terminal-ui.md. Open:
  live-model interaction, non-POSIX terminal verification, full emoji-grapheme/bidi
  shaping and actual provider cache/latency measurements. No new model calls are
  introduced by UI rendering; volatile model_end content does not change billing.

### 2026-11-09 — General file optimization clarification and MCP readiness

- Confirmed the local display route is filename-independent: synthetic app.py,
  data.json and notes.txt all displayed locally, with no model/model_request/tests
  events. Existing tests also cover quoted text filenames and unsafe-path refusal.
  This is bounded guarded text display, not a blanket bypass for arbitrary tasks.
  Writes still need model reasoning, checked edits and acceptance verification;
  batched tools exist, but general write latency has not been measured.
- MCP was already implemented; reviewed rather than rebuilding it. Found and
  reproduced catalog output exceeding its 10,000-byte cap: omitted names increased
  a result to 10,105 bytes. Reserve omission metadata before admitting definitions.
  test_catalog_byte_limit_includes_omitted_tool_names failed before, passed after;
  it also confirms individual lookup of omitted definitions remains available.
- Added test_multiple_mcp_calls_stay_sequential_with_fresh_approval: two calls in
  one model turn each prompt, share cached discovery, record parallel=False, and
  cannot construct a ThreadPoolExecutor. Simulated transport/model responses only.
- Baseline: `set -o pipefail; python3 -m unittest discover -s tests -q`:
  376 tests in 13.650s, OK. Regression: `python3 -m unittest discover -s tests
  -p test_mcp.py -q`: 25 tests in 0.332s, OK. Focused:
  `PYTHONPATH=tests python3 -m unittest test_mcp test_agent test_capabilities
  test_terminal test_session_isolation test_local_reads test_recent_turns -q`:
  133 tests in 8.748s, OK. Full:
  `set -o pipefail; python3 -m unittest discover -s tests -q`:
  378 tests in 13.279s, OK. `python3 -S -m miser mcp --help` and
  `git diff --check` passed. No new runtime dependency, commit, push or live service.
- README clarifies general read/write behavior; MCP guide clarifies omission
  budgeting. Real server integration still requires a host-selected endpoint,
  tool allowlist and authentication environment reference. No credentials were
  requested/read/printed and the untracked root config.json was left untouched.

### 2026-11-09 — Recent turns, display and avoidable response latency

- Prioritized the user's context/UI/latency issues before extending MCP further.
  Baseline `set -o pipefail; python3 -m unittest discover -s tests -q`:
  360 tests in 13.258s, OK. Existing uncommitted work was preserved; no commits.
- Added tests/test_recent_turns.py (16 deterministic tests). Reproduced omitted
  local-read/task context, failed-turn omission, missing history in inspection,
  clipped code, literal final backticks, styled/wide wrapping overflow and lost
  continuation styles, long headings/labels, cropped transcript tails and inability
  to scroll within one long entry. Fixed each at the responsible history/render
  layer. New coverage also checks empty history, session isolation, bounded context,
  exact-once messages and refusing compound edits in the local display parser.
- Final regression command: `python3 -m unittest discover -s tests -p
  test_recent_turns.py -q`: 16 tests in 0.125s, OK. Focused command:
  `PYTHONPATH=tests python3 -m unittest test_recent_turns test_terminal test_ui
  test_tui_app test_tui_screen test_capabilities test_session_isolation
  test_local_reads test_agent test_mcp test_knowledge -q`:
  201 tests in 9.119s, OK. Full command:
  `set -o pipefail; python3 -m unittest discover -s tests -q`:
  376 tests in 13.372s, OK. Earlier intermediate checks exposed failures and were
  corrected; no assertion was weakened or test skipped.
- `git diff --check` passed; `python3 -S -m miser --help` passed without site
  packages. `git diff --name-only -- opencode aider examples pyproject.toml` was
  empty. No reference repositories, dependencies, budgets or benchmark limits changed.
- Extended local parser for the screenshot wording: "i want you to read 4 lines
  from Readme.md and then print here". It now uses Workspace guards, no model or
  tests. A single smoke using a synthetic five-line README measured 11.456 ms
  for that read and 0.057 ms for previous-message recall; model request count 0.
  This is local smoke evidence, not a provider benchmark or guaranteed speedup.
- Existing streaming and read-only parallel batching remain enabled. No live
  provider, cache, MCP or model latency test was run; no socket listener was used.
  Provider latency/retries and gateway cache support still need real measurements.
  Layout coverage uses simulated terminal states/keys; interactive visual review
  and full emoji-grapheme shaping remain open. Historical benchmarks unchanged.
- Updated README, implementation status, roadmap, handover and this memory file.
  MCP remains opt-in; browser/UI automation and delegated workers remain pending.

### 2026-11-09 — HTTP MCP discovery and approved read-only calls

- Baseline: `set -o pipefail; python3 -m unittest discover -s tests -q`:
  337 tests in 13.274s, OK. New regression run reproduced two failures: escaped
  credentials could bypass serialized-string checking, and TUI shutdown could
  leave a pending edit approval worker blocked. Decoded-string credential checks
  and shutdown refusal/release fix both; 23 MCP tests passed (0.204s, later
  verbose repeat 0.200s). No assertion was weakened or test skipped.
- Focused: `PYTHONPATH=tests python3 -m unittest test_mcp test_capabilities
  test_agent test_terminal test_session_isolation test_tui_app test_tui_screen
  test_audit test_knowledge -q`: 197 tests in 10.857s, OK.
- Full: `set -o pipefail; python3 -m unittest discover -s tests -q`:
  360 tests in 13.420s, OK. `git diff --check`, `python3 -m miser mcp --help`
  and `python3 -m miser chat --help` passed. All MCP transport/key-event results
  are simulated; no listener, live MCP/model or benchmark run was used.
- Implemented bounded JSON/SSE HTTP transport, explicit version pins, legacy
  initialization/session cleanup, tool discovery and allowlisted calls. Credential
  references are environment names; known values are refused in arguments/config
  and redacted from results. Ledger events store method/alias/outcome/timing, not
  URLs, auth, arguments or remote errors. RPC completion is not known billing.
- Default disabled; POSIX external no-follow config only, no inline credentials,
  subprocess server command, OAuth, redirects, environment proxies or retries.
  At most four servers, eight tools/server, 32 RPC attempts/task, eight call attempts
  plus up to four legacy cleanup requests. Fresh approval cannot be cached or
  supplied by batch stdin. Server read-only classification remains a host trust
  decision. Unsupported resources/prompts/sampling/MRTR/custom headers are absent.
- Updated setup guide, README, implementation status, roadmap and handover.
  No new runtime dependency, reference-repository changes, commit or push.
  The pre-existing untracked root config.json was left untouched.

### 2026-11-09 — Persistent project knowledge

- Baseline 317 tests OK (12.845s). Final targeted tests 20 OK (0.259s), focused
  172 OK (10.664s), full suite 337 OK (13.126s). `python3 -S -m miser memory
  --help` also passed. No live model calls, remote services or benchmark runs.
- Added miser/knowledge.py and explicit slash/CLI save, list, forget, clear,
  on/off commands. Stores bind to the resolved repository path; copied stores from
  another repository are refused. No model-controlled memory-write tool exists.
- Context is loaded once at task start, bounded, tagged untrusted and inserted in
  user/state data. The task, system prompt and tool profile cannot be overwritten
  by stored text. Plain conversations also get bounded data before the current
  question. No fact contents are recorded in the new ledger metadata event; the
  normal prompt diagnostics/budget include loaded context. No extra model calls.
- Linked facts hash bounded regular UTF-8 source through no-follow descriptor
  access; changes, deletion, symlinks/FIFOs and inaccessible sources make facts
  stale/excluded. Unicode facts remain readable rather than escaped in the prompt.
- POSIX lock serializes writers with a two-second busy timeout. Store writes use
  private temp files, atomic replacement and fsync; replacement failure leaves the
  previous store intact and cleans up temp files. Concurrent host-save tests use
  multiple instances/threads. No power-loss or non-POSIX certification is claimed.
- Added guards for configured credentials, obvious credential assignments and
  control characters, including loaded metadata and linked path text. This is not
  a complete secret scanner. Invalid JSON/schema/depth errors fail closed without
  echoing contents; explicit clear or --no-memory allows recovery/bypass.
- Tests cover fresh sessions, repo isolation, context/store bounds, injected text
  remaining data, stale files, symlinks/FIFOs, concurrency, failed replacement,
  malformed stores, secret refusal, model write refusal, and CLI/slash/conversation
  integration. Earlier targeted failures exposed stale-symlink handling, raw
  metadata credential leakage, Unicode escaping and incomplete review output;
  all were corrected with assertions retained. Prose apostrophes/quotes are no
  longer parsed as shell-style tokens by /remember; only an optional path is parsed.
- Updated README, status, handover, roadmap and this log. Current instruction-size
  estimates: coding 726 tokens, read-only 218 (UTF-8/4, not billing), excluding
  state/history/tools. Prior benchmark numbers and golden limits unchanged. No new
  dependencies, reference-repository changes, commits or pushes. The pre-existing
  untracked config.json was left untouched. Next is MCP integration.

### 2026-11-09 — Read-only reasoning and in-task clarification

- Reproduced 299 passing tests before changes (12.791s). Added 18 deterministic
  capability tests; final targeted 18 OK (0.295s), focused 174 OK (11.059s), full
  317 OK (12.862s). CLI --help also works with site packages disabled (-S).
- Added inspect/research/coding profiles with shared schema/dispatch allow sets.
  Read-only requests have no acceptance or architect calls; code questions can
  inspect actual files instead of answering from only a repository outline.
  CLI --profile provides explicit enforcement; only coding needs --test-command.
- Added bounded ask_user questions (500 chars, <=5 choices, <=3 questions per task)
  and answers (<=2000 chars). Live answers resume the same model context. No input
  channel/declined answers terminate needs_input after that model call and expose
  the pending question in CLI/TUI output. No raw answer in clarification events.
- Added TUI numbered/free-text input and cancellation/EOF release. Reproduced and
  fixed composer text being overwritten after an answer. Mixed question/tool
  batches cannot run preplanned writes. Batch/--exec refuses clarification and
  approval prompts even if stdin or a custom reader is interactive.
- Routing coverage includes advice vs delegated changes, read-only negation,
  filenames such as edit.py, discovery tasks, and reviews that mention deletion
  without authorizing it. Existing conversational tests now use conversation
  prompts; dedicated new tests cover repository questions. Catalog assertion now
  expects 19 because ask_user is an intentional addition, not a skipped assertion.
- Local UTF-8/4 size estimates: coding definitions 1808 + instructions 701 tokens;
  inspect 789 + 196; research 1064 + 196. These omit state/history/framing and are
  not provider billing or measured latency savings. All new model/UI checks are
  scripted/simulated; no live model/service runs were made.
- README, implementation status, handover and roadmap updated. Next is bounded
  persistent project knowledge. Runtime dependencies, shell allowlists, file
  protections, golden limits and numerical benchmark evidence unchanged. Prior
  uncommitted work retained; no commit or push.

### 2026-11-09 — Local file-read optimization and branding

- Checked `runs/session-1c3a2ba35d89/ledger.json`: baseline acceptance cost 12.942s;
  three model completions totaled 59.361s, including retry handling. File lookup
  and read tools took 0.001s each. Receipt total: 7,265 provider-reported tokens.
- Implemented a conservative full-match route for explicit file displays and
  first-N-line requests, with no model or acceptance command. Unique case fallback
  handles Readme.md -> README.md without a repository-wide search. Path/symlink/
  sensitive-file guards, output limits and per-task receipts are retained.
- Real local smoke of the exact screenshot request displayed `# MISER` in 0.0026s,
  with 0 model calls/tokens, 0 test runs and one host read event. This is one local
  measurement, not an LLM benchmark or a broad latency guarantee.
- Fixed the N-like pixel M and added a plain MISER caption. Added 9 tests, including
  TUI entry, guards, case ambiguity, quoted names, output caps and undo preservation.
  Focused tests caught “show commands” being misrouted; reserved help now takes
  precedence. Also fixed first-line words inside quoted filenames being mistaken
  for a line-limit instruction. No assertions were weakened.
- Verification: baseline 290 OK (12.722s); final local tests 9 OK (0.031s);
  focused 78 OK (2.517s); full 299 OK (12.652s). An earlier full run failed the
  help-routing regression before the correction. No live model calls or new deps.
- Updated README and the ordered capability queue. No commit or push. This file
  is maintained by the development assistant; MISER does not automatically load
  or learn this file as cross-session reasoning memory.

### 2026-11-09 — Skeptical audit

- Reproduced a clean `6898ab5` baseline and 249 passing tests. Added 41 audit
  checks; full suite now passes 290. Focused run passed 180 tests.
- Fixed checked/staged writes, partial-write recovery, stale patch and same-file
  version checks, CRLF preservation, hunk offsets and final-newline handling.
- Enforced program-name validation and fresh approvals, isolated jobs per task,
  and cleaned up subprocess groups on success, cancellation and interruption.
- Fixed ordered activity/results, malformed usage/arguments, failure-time test
  invalidation and evaluation early stop for unmetered responses; repaired undo
  conflict handling and known-credential web diagnostics; blocked legacy private IPv4.
- Open boundaries: DNS pinning, same-user path races, no power-loss durability
  guarantee, model injection resistance and richer compaction digests. No new
  live calls, dependencies, commits or pushes. Earlier logs remain historical.

### 2026-11-09 — Session 9: Phase 7 (golden-task evaluation, real runs)

- No new harness code: `miser/evaluation.py` already implemented `miser evaluate`,
  `GOLDEN_LIMITS = {"max_model_calls": 4, "max_provider_tokens": 6000}` and
  `report.json`. This session recorded real runs and documented them.
- Confirmed the default-budget failure cause from `runs/golden-python-20261109a`:
  all four allowed calls went to orientation (`find_files`, two `zoom` reads,
  `write_todos`) and the loop ended `budget_exhausted` before any edit. Provider prompt
  grew 2,412 → 2,461 → 2,770 → 3,367 per call.
- Live runs (real gateway, provider-reported usage, `usage_complete: true`, 0 failed
  requests, 0 compactions):
  | Run | Status | Calls | Tokens | Wall clock |
  | --- | --- | --- | --- | --- |
  | `runs/golden-python-20261109a` (default) | `budget_exhausted` | 4 | 11,098 | 46.1 s |
  | `runs/golden-python-20261109b` (40k) | `tests_passed` | 5 | 15,000 | 41.3 s |
  | `runs/golden-js-20261109a` (40k) | `tests_passed` | 5 | 14,937 | 41.8 s |
- Docs updated: `docs/benchmark-results.md` (three rows + analysis),
  `docs/agent-roadmap.md` (Phase 7 status), `docs/implementation-status.md` (Phase 7
  section), `HANDOVER_PROMPT.md` (Phases 1–7).
- Coverage gap stated: only the bug-edit fixture is recorded in both languages; the
  add-test, cross-file refactor and lint-fix tasks are not run yet.
- Tests unchanged at 249 (docs-only change).

### 2026-11-09 — Session 8: Phase 6 (parallel read-only tools, tighter compaction)

- **Parallel read-only batches.** `miser/tools.py` gained `READ_ONLY_TOOLS`.
  `run_agent` now runs a step concurrently only when every call parsed, every tool is
  read-only, and there are at least two calls. Starts are emitted on the main thread in
  model order; results arrive via `as_completed`, but tool messages, `memory.observe`
  and the `tests_passed` early exit are emitted in call order, so transcripts match a
  sequential run. Workers never call `progress`/`activity`. A `tool_batch` ledger event
  records model-visible batch latency (receipt ignores unknown kinds, so no schema
  change).
- **Tighter compaction.** `compact_digest` keeps structured summary keys (path, counts,
  exit status, …) capped at `DIGEST_LIMIT=600` chars instead of a blind truncation. A
  bounded `decisions` deque (`DECISION_LIMIT=300`) is injected into history only when a
  real compaction happens, so long sessions keep earlier decisions.
  `compaction_threshold` uses `token_budget * min(COMPACTION_RATIO, 0.55)` when the
  largest tool output exceeds `token_budget * 0.12`, else `token_budget * 0.75`.
- **Concurrency safety.** `miser/ledger.py` uses `threading.RLock`; `miser/web.py`
  reserves search budget atomically under a `Lock`.
- Tests: 7 new in `tests/test_agent.py` (parallel order, sequential fallback, mixed
  tools, single call, unparsed call, digest/decisions, adaptive threshold) and
  `BudgetConcurrencyTests` in `tests/test_web.py` (12 threads, `max_calls=5`, no
  over-spend). One decisions test initially hit `budget_exhausted` because
  `ledger.total_tokens` is cumulative; fixed by patching `COMPACTION_RATIO` to 0.05 and
  raising `token_budget` to 20000 so the loop reaches `step_limit` while compacting.
- Verification: focused `python3 -m unittest tests.test_agent tests.test_web -q` → 51 OK;
  full `python3 -m unittest discover -s tests -q` → **249 OK** (~7.9 s).
- Measurement, labelled honestly: real `zoom` calls (medians of 7) took 0.5/0.9/2.3/6.6
  ms sequential vs 0.4/1.5/3.6/10.3 ms parallel for 1/2/4/8 calls — parallel is ~0.6×,
  i.e. slower, for microsecond-scale local work. A simulated 150 ms per-call latency
  took 601 ms sequential vs 151 ms parallel (~4.0×). No live remote concurrency timing
  was recorded: this host cannot bind sockets, so `tests/test_web.py` patches
  `_open_once` / `post_json`.
- Docs updated: `docs/implementation-status.md` (Phase 6 section at top),
  `docs/agent-roadmap.md` (Phase 6 status block), `docs/reference-design.md`
  (compaction row no longer says "No summarization call"), `HANDOVER_PROMPT.md`
  (Phases 1–6, 249 tests), this file.

### 2026-11-09 — Session 7: `answered` status, Phase 5 model-driven run recorded

- **Misleading chat status fixed.** `miser/agent.py` used to finish every no-tool-call
  reply as `incomplete`, which the result panel rendered as a yellow "no more tool
  calls" warning even when the model had simply answered a question. Now a non-empty
  text reply finishes as `answered` (`agent_message` still stores the text); an empty
  reply stays `incomplete`, and a `finish_reason == "length"` reply stays `truncated`.
  `miser/ui/render.py` gained an `answered` label with the neutral `g.info` glyph, so it
  cannot fall into the red failure branch. Nothing treats `answered` as passing tests.
- Tests updated for the new semantics: `tests/test_agent.py`
  `test_model_cannot_claim_success_without_acceptance` now asserts `answered` and that
  the status is not `tests_passed`, plus a new `test_empty_reply_is_incomplete`;
  `tests/test_session_isolation.py` asserts `answered` for the second-task no-op.
- Verification: focused `python3 -m unittest tests.test_agent tests.test_session_isolation -q`
  (28 tests OK), then full `python3 -m unittest discover -s tests -q` — **241 tests OK**
  (exit 0, ~7.2s).
- Live check: `python3 -m miser chat --no-tui --no-stream --model
  gemini/gemini-3.5-flash-lite --exec "Read pricing.py and explain in one sentence what
  discount() computes. Do not modify any files."` → session `runs/session-764157a062c5`
  ended `status: "answered"`, 7 model requests, 7 tool calls, 17,808 provider tokens
  (17,642 in / 166 out), no modified files, empty `patch.diff`. The panel printed
  "· answered".
- Phase 5 model-driven run now recorded (made at the end of session 6):
  `runs/session-e4d476853be7`, the `docs.python.org` `Path.read_text` fetch task, 4
  model requests, 4 tool calls, 18,777 provider tokens, correct cited answer.
- Docs updated to match: `docs/implementation-status.md` (new final-answer section plus
  the model-driven web run), `docs/agent-roadmap.md` (Phase 5 status block),
  `HANDOVER_PROMPT.md` (241 tests, recorded run, `answered`).

### 2026-11-09 — Bifrost login, Phase 5 (web search and fetch)

- **Bifrost "No setup token is configured" is a stale tab, not a live fault.** The
  dashboard config lives at `~/.config/bifrost/config.json`; giving it a literal
  `setup_token` string is the portable fix, because the `npx @maximhq/bifrost`
  wrapper (`bin.js` v1.6.3) forwards only app-dir/host/log-level/log-style/port and
  would drop a `--setup-token` flag. The same token is in
  `~/.config/bifrost/setup-token.txt`; both files are mode 600 and the token must
  never be printed. After a detached restart:
  `setsid nohup npx --yes @maximhq/bifrost > /tmp/bifrost-restart.log 2>&1 < /dev/null &`
  the session endpoint reports `"setup_token_configured": true` and
  `"setup_required": true` with `auth_type: none`. `/api/config` answers 200 with an
  `X-Bifrost-Setup-Token` header and v2.5.0 is serving. Inference was re-confirmed
  (`/v1/models` 200, chat completion 200). There is no discovered API route to create
  the admin account (`/api/auth/setup`, `/api/session/setup`, `/api/session/login`,
  `/api/auth/login` are all 404), so dashboard login needs a human in a browser;
  inference does not need it. Fix for the user: hard-reload `http://localhost:8080/login`
  (Ctrl+Shift+R) and paste the token from `cat ~/.config/bifrost/setup-token.txt`.
- **Phase 5 implemented**: `miser/web.py` (`WebAccess`, `check_url`, `_open_once`,
  `_NoRedirect`, `_TextExtractor`, `html_to_text`), wired into `tools.py` (18 schemas,
  dispatch, per-run budget 8 shared by both tools), `agent.py` (system-prompt rule,
  summary keys, ledger detail), `ui/render.py` (`web` / `fetch` labels) and
  `ledger.py` (`web_calls`). Contract: fetched text is untrusted data in a `tool`
  message, never system-prompt text; https only except loopback test doubles;
  userinfo refused; private/loopback/reserved hosts refused unless
  `MISER_WEB_ALLOW_PRIVATE=1`; redirects off by default with each hop re-validated
  (max 3); 500,000-byte body cap, 8,000-char returned text cap; non-text refused.
  Hostnames are checked literally — this is a policy guard, not a DNS sandbox.
- **Tests**: `tests/test_web.py`, 18 cases. First run had one failure because the
  test expected `http://localhost` to pass the default guard; fixed the test to
  assert the loopback guard still applies and to opt in with `allow_private=True`.
  Full suite: **240 tests OK**. Fetch tests patch `miser.web._open_once` and
  `miser.web.post_json` because this host cannot bind sockets — labelled simulated.
- **Live web check (real services, host script, not model-driven).** After
  `miser.cli.load_env()`, `WebAccess.search("python 3.12 pathlib read_text encoding")`
  returned 3 real Tavily hits. The first result URL
  (`https://stackoverflow.com/questions/49428723/...`) failed with
  `RuntimeError: Fetch failed: Page returned HTTP 403` — site-level bot protection,
  not an implementation fault, and the tool reported it cleanly instead of retrying.
  Two fetch-friendly pages then succeeded: `https://docs.python.org/3/library/pathlib.html`
  and `https://realpython.com/python-pathlib` both returned HTTP 200 `text/html`,
  converted to text, capped at 8,000 chars with `truncated: true`. Real Python's
  redirect to the trailing-slash URL was followed and re-validated by `_follow`, so
  the live redirect path is now confirmed too. Remaining gap: a model-driven task,
  not the tools themselves.

### 2026-11-09 — Phase 4 planning and progress

Completed:

1. **`miser/todos.py` (new).** `TodoList` owns the ordered plan: `MAX_TODOS = 20`,
   `MAX_TASK_CHARS = 200`, validated `update(items)` that normalises whitespace,
   strips empties and rejects non-string/oversized entries, a monotonically
   increasing `revision`, `stale_checks`, and read-only `summary()` / `state()`
   views. `progress()` reports `total`, `completed`, `next_item` and `all_done`.
   A rejected update leaves the previous list untouched.
2. **`miser/tools.py`.** 16th schema `write_todos`, with the invariant that a
   successful call must re-emit the whole list (`in_progress` at most once, at most
   one item marked in progress). `invoke()` validates the argument set is exactly
   `{"todos"}`, records `ledger.record("todos", ...)`, and returns
   `{revision, total, completed, next_step, items}`.
3. **`miser/agent.py`.** `SYSTEM` tells the model to keep the list current and
   re-emit it after each completed item. `build_messages()` emits `state["todos"]`
   on every step, so the plan is always in context whether or not the model repeats
   it. `run_agent` tracks whether the turn's tool calls included `write_todos`; if a
   turn did work without re-emitting the plan, it sets `plan_reminder` and
   increments `stale_checks` — but **only when `step + 1 < max_steps`**, because a
   final turn cannot act on the nudge (this guard fixed the two failures seen in
   the first focused run). `SUMMARY_KEYS` gained the todo result fields so they
   survive compaction.
4. **`miser/ui/render.py`.** `TOOL_LABELS["write_todos"] = "plan"`,
   `tool_detail()` → `"d/t done"`, and `todo_list(...)` renders one compact
   checklist (`✔`/`○`, ASCII `x`/space when unfancy) with a header.
5. **`miser/terminal.py` / `miser/tui/app.py`.** Both render the checklist once,
   after a successful `write_todos` tool result — one update per step, not a dump.
6. **`tests/test_todos.py` (new, 14 tests).** Validation rejections, ordering and
   whitespace normalisation, revision bump, immutable `progress()`/`state()`,
   failed-update preservation, tool invoke + ledger event, exact-argument check,
   validation-error path, stale vs fresh plan reminder, checklist rendering, and
   `tool_detail`. `tests/test_agent.py`'s schema assertion now requires
   `write_todos`.

Verification actually run:

- `python3 -m unittest tests.test_todos -v` → **14 tests, OK** (0.142s).
- `python3 -m unittest discover -s tests -q` → **222 tests, OK**, exit 0.

Not verified / not done:

- No live model run has used `write_todos`; the acceptance evidence is unit tests
  over the runner, the loop and the renderer, not a model-driven multi-step task.
- The re-emit instruction is prompt-level. MISER nudges and re-injects the plan, but
  it cannot force a model to rewrite the list.

---

### 2026-11-09 — Phase 3 supervised execution (approved by the user)

Completed:

1. **`miser/execution.py` (new, ~256 lines).** `run_command` with
   `action = run | status | stop`, an `argv` array, `background`, and `job_id`.
   - `DEFAULT_ALLOWLIST` uses prefix rules: `python3 -m unittest`, `python3 -m pytest`,
     `python3 -m mypy`, `pytest`, `ruff`, `mypy`, `node --test`, `git status`,
     `git diff`.
   - `SHELL_METACHARACTERS = ";&|<>$`\n\r()"` — any occurrence in any argument is a
     refusal, and the process is spawned with `shell=False` always. There is no code
     path that reaches a shell.
   - `sanitised_env` passes only `SAFE_ENV_KEYS` (PATH, HOME, LANG, LC_*, TERM, TMPDIR,
     SYSTEMROOT, PYTHON*); credentials in `.env` never reach the child.
   - Limits: `MAX_ARGV = 32`, `MAX_ARG_LENGTH = 500`, `OUTPUT_CAP = 8000`,
     `MAX_JOBS = 8`.
   - Approval: a callback returning `True` runs once, `"always"` adds the exact argv
     tuple to a per-session set (so the next identical invocation is silent), `False`
     refuses. **No callback ⇒ refuse**, which is why the headless run path refuses.
   - Real exit status is carried through unchanged; `0` and non-zero are both returned
     with stdout/stderr, not collapsed into an exception.
   - Background jobs write to `{repo}/.miser/jobs/<job_id>.log`, registered in a
     process-local `_JOBS`; `stop` sends `SIGKILL` to the process group then the
     process. `status` falls back to a surviving log file for an unknown id.
2. **`miser/tools.py`.** 15th schema `run_command`; `ToolRunner.__init__` gained
   `command_approval`, `command_allowlist`, `command_timeout` (120s),
   `max_command_runs` (10) and holds `self.commands = CommandSupervisor(...)`;
   `invoke()` routes `run_command`.
3. **`miser/agent.py`.** `SYSTEM` describes the tool's real limits (allowlist,
   approval, no shell, may be refused when headless, `background=true` +
   `action=status`). `SUMMARY_KEYS` extended with `command`, `argv`, `output`,
   `output_truncated`, `job_id`, `running`, `elapsed_seconds` so results survive
   compaction.
4. **`miser/terminal.py`.** `prompt_command_approval(command)` → `True` / `False` /
   `"always"`; `task()` passes it as `command_approval`.
5. **`miser/tui/app.py`.** `_approval_is_command` flag, `request_command_approval`,
   and a command branch in `_handle_approval_key` (`a` selects `"always"` without
   clearing `confirm_edits`).
6. **`tests/test_execution.py` (new, 8 tests).** Allowlisted run; non-zero exit
   preserved; metacharacter refusal; unlisted binary refusal; approval refusal;
   missing approval channel; `"always"` suppresses the repeat prompt; background
   start → status → stop.

Verification actually run:

- `python3 -m unittest tests.test_execution -v` → **8 tests, OK** (0.749s).
- `python3 -m unittest discover -s tests -q` → **208 tests, OK**, exit 0, 12.816s.

Not verified / not done:

- No live model run used `run_command`; the Phase 3 acceptance is proven by unit
  tests against real `python3 -m unittest` invocations, not by a model-driven task.
- `ruff`/`mypy` allowlist entries are unverified as installed on this machine.
- App-level guards are not an OS sandbox.

---### 2026-11-09 — truncation status, live gateway probe, first real smoke run

Completed:

1. **Truncation is now visible.** `miser/agent.py`: when a reply has no tool calls and
   `finish_reason == "length"`, the run finishes with status `truncated` (carrying
   `finish_reason` and a note) instead of `incomplete`. `miser/ui/render.py` gained a
   `truncated` label and a hint line; `miser/tui/app.py` shows "output truncated" in
   the status line. New test
   `test_length_capped_reply_is_reported_as_truncated` in `tests/test_agent.py`.
2. **Live gateway probe (no secrets printed).** `gemini/gemini-3.5-flash` is 429 for
   tool-bearing requests; `gemini-3.5-flash-lite` works; `gemini-2.5-flash-lite` is a
   listed route that returns 404. `/models` lists 61 models.
3. **First real end-to-end smoke run.**
   `timeout 280 python3 -m miser smoke --language python
   --model gemini/gemini-3.5-flash-lite --out runs/smoke-phase12-20261109` →
   `tests_passed`, 4 model calls, 6 tool calls, 0 failed requests, 8,948 provider
   tokens, 2 test runs, 0 compactions, 0 fallbacks. Component prompt estimates:
   instructions 1,752, state 1,693, history 1,637, tool definitions 4,972,
   tool context 1,046. Ledger: `runs/smoke-phase12-20261109/result/ledger.json`.
4. **Docs.** `docs/benchmark-results.md` records the smoke run as a single real run
   (explicitly not a benchmark); `HANDOVER_PROMPT.md` and
   `docs/implementation-status.md` refreshed to 200 tests.

Verification actually run:

- `python3 -m unittest tests.test_agent -q` → 24 tests, OK.
- `python3 -m unittest tests.test_ui tests.test_tui_app -q` → 36 tests, OK.
- `python3 -m unittest discover -s tests -q` → **200 tests, OK**, exit 0.
- Smoke run above is real provider traffic; its ledger is on disk.

Not verified / not done:

- No Phase 1/2 before/after comparison; the "before" surface no longer exists.
- Phase 3 remains unimplemented pending explicit approval.

---

### 2026-11-09 — Phase 1 + Phase 2, compaction accounting fix

Completed:

1. **`miser/workspace.py`**
   - `_glob_match()` helper: `**/` also matches zero directories, so
     `find_files("**/*.py")` includes root-level files.
   - `scope(cwd)`: normalises and strips repeated leading `./`; rejects non-directories.
   - `find_files(pattern, limit=100, cwd="")`: globs through `self.path()` when the
     pattern has no `**`, else filters `self.files()`; bounded at 5000.
   - `search(query, limit=20, context=0, cwd="")`: additive `cwd`/`context`; result
     shape unchanged unless scoped.
   - `read_many(reads, max_chars=24000)`: up to 8 `{path, offset, limit}` windows,
     registers snapshots/reads so an `edit` can follow immediately, per-file
     `{"error": ...}` without aborting the batch.
   - `write_file(path, content)`: new-file creation with guards (non-str, empty,
     >200 000 bytes, existing file, symlink, missing parent directory);
     returns `{"path", "version", "created": True}`.
   - Zero-match edit errors in `edit`, `edit_batch`, `_apply_hunk` now append the
     nearest matching region with line numbers.
2. **`miser/terminal.py`** — `undo()` deletes files recorded with the
   `originals[path] = None` sentinel; `compute_diff()` renders created files as
   `/dev/null → b/path`.
3. **`miser/tools.py`** — schemas for `find_files`, `read_many`, `write_file`
   (14 total); extended `search` schema; `preview_edits` handles `write_file` via
   `self._preview(path, "", content)`; `invoke` routes the read-only pair through
   `getattr(self.workspace, name)` and `write_file` through the edit/guard/approval
   group.
4. **`miser/agent.py`** — `SYSTEM` prompt mentions `find_files`, `read_many`,
   `write_file`. Compaction fix: a pass that frees no prompt tokens now breaks out
   *before* recording, so receipts no longer report zero-gain "savings". This fixed
   `test_long_task_compacts_context_below_prompt_budget`.
5. **Tests** — 10 new cases: 7 in `tests/test_workspace.py`, 3 in `tests/test_agent.py`
   (`test_schema_covers_retrieval_and_write_tools`,
   `test_write_file_tool_creates_file_and_protects_tests`,
   `test_read_many_tool_version_edits_without_zoom`). Also fixed the broken
   `test_write_file_creates_new_files_only` setup.
6. **Docs** — `HANDOVER_PROMPT.md` (189 → 199 tests, date), `docs/implementation-status.md`
   (test count, new "Retrieval and edit-surface update" section, zero-gain compaction
   bullet), `docs/agent-roadmap.md` (Phase 1 and Phase 2 marked implemented, with the
   honest note that their acceptance *measurements* are not recorded).

Verification actually run:

- `python3 -m unittest tests.test_workspace tests.test_agent -q` → 46 tests, OK.
- `python3 -m unittest discover -s tests -q` → **199 tests, OK**, exit 0.
- Import check: 14 tool schemas, names as listed above.

Not verified / not done:

- No live model run, so Phase 1/2 acceptance numbers (tool-call count, edit-failure
  rate) do not exist. The "before" numbers would also require reverting the surface,
  so the honest baseline is unavailable.
- Nothing committed (git broken).

---

## Next steps

The following are pending, not completed. `HANDOVER_PROMPT.md` contains the detailed
acceptance contract and commands for a new agent. Do not redo the native TUI.

1. **Immediate feature: guarded file deletion.** The user's delete cat.txt/create
   cat2.txt essay task is not supported end to end. Implement a dedicated version-
   checked operation with fresh approval, safe deletion diffs, session tracking and
   conflict-aware undo. Test rejection, stale reads, symlinks/traversal, sensitive/
   acceptance paths, empty files, modes/line endings, cancellation and mixed-operation
   failures using temporary fixtures. Never add rm/arbitrary shell as a workaround;
   never touch the user's actual untracked cat.txt/config.json as a test.
2. **Reduce file-task overhead.** Smaller host-enforced capability sets; direct
   reads for supplied paths and bounded batches; fewer redundant search/todo/model
   turns. Current /checks manual is explicit and unverified, not an automatic safe
   file classifier. Do not claim it resolves provider delays or unsupported actions.
3. **Improve verification selection.** Carefully scoped checks/cache, with complete
   invalidation and no cached-pass claim for unknown or changed state. Required
   remains default. Never silently mark skipped/manual edits verified.
4. **Measure before claiming improvement.** Cover reads, conversation, simple file
   creation, delete/create, real bug fixes, failed tests, 429 and cancellation.
   Separate provider-reported usage, local estimates and host duration. Existing
   streaming/parallel reads are implemented; prompt caching/live speedup is unverified.
5. **Safety priority alongside feature work.** DNS-pinned transport and descriptor-
   relative file operations, then ledger crash durability and read_many compaction.
   These are unresolved audit boundaries; app guards are not an OS sandbox.
6. **Later capabilities/evidence.** Full conversation resume, successful live
   gateway/MCP validation, broader evaluation fixtures, browser/UI verification,
   budgeted delegated workers. Keep golden limits/recorded numbers unchanged.

## What the user may need to do

- Launch with the project interpreter; system Python lacks Textual. Restart MISER
  after code changes. Activation lets the familiar python3 command use that venv.
- For lightweight tasks explicitly choose /checks manual (edits unverified); restore
  /checks required for coding verification. This does not enable file deletion.
- A supplied screenshot showed 429 responses; current gateway/model availability
  was not freshly probed. If a live run is appropriate, use
  gemini/gemini-3.5-flash-lite, label it real and record actual results.

## Useful commands

Run from `/home/aman-kumar-sharma/Desktop/fresh-code`:

```bash
.venv/bin/python -m miser chat . --tui
# Alternative for this terminal session:
source .venv/bin/activate
python3 -m miser chat . --tui

# Verification before the next implementation:
set -o pipefail; .venv/bin/python -m unittest discover -s tests -q
PYTHONPATH=tests .venv/bin/python -m unittest test_latency test_execution test_workspace test_terminal -q
python3 -S -m miser --help
.venv/bin/python -m miser chat . --no-tui
git diff --check
```

The recorded latest full suite is 430/81.431s OK, not rerun for this documentation
update. HEAD is still 6898ab5; later work is uncommitted. Preserve the working tree.
