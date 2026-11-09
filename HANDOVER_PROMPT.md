# MISER — Handover & Master Execution Plan

You are taking over **MISER**, a high-performance, lightweight Python coding agent inspired by **OpenCode** and **Aider**. Continue directly from the current implementation; do not rebuild it from scratch.

---

## 1. Project Context & Environment

- **Project Root**: `/home/aman-kumar-sharma/Desktop/fresh-code`
- **Language / Runtime**: Python 3.12 (target: Python 3.11+ compatibility, standard-library-first).
- **Test Suite Status**: **240 tests passing** (`python3 -m unittest discover -s tests -q`).
- **CLI Entry Point**: `python3 -m miser` (or `pyproject.toml` console script).
- **Inference Gateway**: Local Bifrost proxy at `http://localhost:8080/openai`.
  - Bifrost provides an OpenAI-compatible REST API (`/openai/chat/completions`) for multi-provider routing (Google Gemini, Anthropic Claude, OpenAI, etc.).
  - Default Model: `gemini/gemini-3.5-flash`.
  - Virtual Key header: `x-bf-vk: <BIFROST_VIRTUAL_KEY>` loaded from `.env`.
- **Reference Repositories**:
  - `opencode/` — Reference for terminal UI, session compaction, TUI architecture, and tool loop UX.
  - `aider/` — Reference for PageRank repository maps (`repomap.py`), whitespace/fuzzy edit matching (`editblock_coder.py`), and Git workflows.

---

## 2. Current Architecture & Completed Work

All foundational and interface improvements have been implemented and verified:

1. **Intent Classification & Conversational Routing** ([`miser/intent.py`](miser/intent.py)):
   - Unwanted tool execution bug fixed: greetings (`"hi"`) return standard CLI welcome without calling models or editing files.
   - Conversational questions (`"how are you"`, `"are you doing fine"`, `"what happened?"`) route to the live model via Bifrost with real-time token streaming and multi-turn conversational history.
   - Casual praise (`"this great"`, `"looks good"`) is acknowledged cleanly without crashing or demanding `/test COMMAND`.

2. **OpenCode-Style Flagship Terminal** ([`miser/terminal.py`](miser/terminal.py), [`miser/formatting.py`](miser/formatting.py)):
   - **Metadata Card**: Clean bordered status card (`format_card`) displaying Workspace, Git Branch & dirty status, Model, Gateway, Acceptance Command, Budget, and Session Token totals.
   - **Interactive Prompt**: Sleek cyan-styled `miser › ` prompt with plain-text fallback.
   - **Readline Autocompletion**: Tab completes slash commands (`/help`, `/status`, `/model`, `/test`, `/diff`, `/undo`, `/run`, `/confirm`, `/autocommit`, `/history`, `/budget`, `/map`, `/receipt`, `/clear`, `/exit`) AND workspace repository file paths.
   - **Command Center (`/help`)**: Grouped into Task & Testing, Model & Accounting, and Workspace & Session.
   - **Task History (`/history`)**: Color-coded badges (`[tests_passed]`, `[budget_exceeded]`), tokens spent, and session tallies.
   - **Approvals & Diffs**: Interactive edit preview (`/confirm on`), manual test runner (`/run`, 0 tokens), and snapshot revert (`/undo`).
   - **Session Continuity**: `--resume` flag to restore past session metrics; `--auto-commit` flag to automatically commit passing edits to Git.

3. **Aider-Style Robust Edits & AST Symbol Caching** ([`miser/workspace.py`](miser/workspace.py)):
   - **Whitespace-Tolerant Edits**: Handles trailing whitespace variations and uniform leading indentation shifts while preserving strict single-occurrence uniqueness.
   - **Nearest Line-Number Diagnostics**: When an edit fails to match, outputs actionable line numbers (e.g., `Similar code exists around line 24. Use zoom('pricing.py', level=2, ...)`).
   - **AST Symbol Caching**: Caches parsed symbols keyed by `(filename, mtime_ns, size)` in `Workspace.symbol_cache`, making `repo_map` sub-millisecond on subsequent turns.

4. **Accounting & Guardrails** ([`miser/ledger.py`](miser/ledger.py), [`miser/agent.py`](miser/agent.py)):
   - Distinguishes authoritative provider billing from local diagnostic estimates.
   - Records failed requests as `model_error` with `usage_known=False` (never recording unknown spend as zero-cost success).
   - Guarded text operations: exact file hash checking, sensitive file protection (`.env`, secret suffixes), path traversal boundaries.

---

## 3. Master Execution Plan: Phase-by-Phase Roadmap

> **Status (2026-11-09):** Phases 1–7 are implemented and covered by tests (249 passing via
> `python3 -m unittest discover -s tests -q`). Phase 7 recorded three real evaluations with
> the existing `miser evaluate` harness: Python and JavaScript both solved the bug-edit
> fixture in 5 model calls and 15,000 / 14,937 provider tokens, while the default-budget
> run ended `budget_exhausted` after four orientation calls and no edit. All three fail
> the fixed golden limits (4 calls, 6,000 tokens): `golden_tasks_passed: 0` and the CLI
> exits 1 even on solved tasks, which is the grader behaving correctly. The receipt's
> per-component token block is cumulative, not per request; per call the fixed overhead
> is ≈2,800 estimated tokens (663 instructions + 1,696 tool definitions), so the
> 6,000-token ceiling allows about two calls. Only the bug-edit fixture is recorded; the
> add-test, cross-file refactor and lint-fix tasks remain unrecorded. Phase 5 added
> `web_search` and `fetch_url`
> with the untrusted-content contract; real search and fetch paths were exercised by a
> host script (3 Tavily hits, two HTTP 200 page fetches, one live redirect), and a
> model-driven task (`runs/session-e4d476853be7`) cited a fetched URL correctly. The
> injected-instruction half is unit-tested only, because it needs a fixture HTTP server
> and this host cannot bind sockets. Phase 6 runs independent read-only tools on a small
> worker pool with order-preserving results, stores structured compaction digests,
> re-injects recent decisions after a real compaction, and lowers the threshold to 55%
> when one tool result is large. Real local reads are slightly slower in parallel;
> simulated network-bound calls were about 4× faster. A text-only final reply now
> finishes as `answered` rather than `incomplete`; an empty reply stays `incomplete`.
> Bifrost is listening again, so its golden run is no longer blocked. See
> [`docs/implementation-status.md`](docs/implementation-status.md) and
> [`docs/benchmark-results.md`](docs/benchmark-results.md) for what is measured versus pending.

Finish the remaining capabilities to bring MISER to full parity with OpenCode and Aider. Execute strictly phase by phase, verifying tests after every change.

### Phase 1: Atomic Multi-File Changes & Unified Diff Engine
- **Objective**: Expand from single-file edits to atomic multi-file changeset execution.
- **Tasks**:
  1. Add an atomic multi-file edit transaction to [`miser/workspace.py`](miser/workspace.py): if a task edits multiple files (e.g., `pricing.py` and `tests/test_pricing.py`), verify all preconditions before writing; if any edit fails, roll back all modified files in the batch.
  2. Implement an Aider-inspired unified diff patch parser (`apply_unified_diff`) as an optional edit mode alongside exact replacement, supporting standard git-style unified diff blocks.
  3. Update `ToolRunner.invoke("edit")` to record cumulative multi-file diff previews.
- **Verification**: Write unit tests in `tests/test_workspace.py` covering multi-file batch editing and rollback on partial failure.

### Phase 2: PageRank Reference Graph Repository Map
- **Objective**: Upgrade `Workspace.repo_map()` from a flat symbol list to an Aider-style reference graph.
- **Tasks**:
  1. Inspect `aider/aider/repomap.py` for its symbol graph weighting and PageRank algorithm.
  2. Implement a standard-library graph model in [`miser/repomap.py`](miser/repomap.py):
     - Extract definition identifiers (classes, functions, methods) using `ast` for Python and regex for JS/TS.
     - Extract reference identifiers across all files.
     - Build an adjacency matrix of definition-to-reference occurrences and compute rank scores.
  3. Ensure repository maps prioritize symbols most relevant to the user's task or query within the token budget.
  4. Persist the symbol graph to `.miser/cache/repomap.json` with cache validation via file modification timestamps.
- **Verification**: Add `tests/test_repomap.py` verifying PageRank ranking on sample multi-file Python and JS codebases.

### Phase 3: Recursive Context Compaction (OpenCode Architecture)
- **Objective**: Prevent unbounded prompt expansion and maintain tight token budgets across long interactive sessions.
- **Tasks**:
  1. Inspect `opencode/opencode/packages/core/src/session/compaction.ts` for how OpenCode compacts older conversational turns.
  2. In [`miser/memory.py`](miser/memory.py) and [`miser/agent.py`](miser/agent.py):
     - Track active working memory vs historical turns.
     - When context reaches 75% of budget, trigger compaction: summarize older completed steps, decisions, and tool outputs into a concise architectural breadcrumb.
     - Drop raw tool JSON results from past turns while keeping the latest zoom snapshot and current test status.
  3. Ensure all compacted tokens are accurately tracked in [`miser/ledger.py`](miser/ledger.py).
- **Verification**: Add test in `tests/test_agent.py` simulating a 12-step task and asserting that prompt size remains bounded below 3,500 tokens.

### Phase 4: Model Fallbacks & Architect-Editor Separation
- **Objective**: Robust model resilience (e.g. handling HTTP 429 quota limits or rate exhaustion).
- **Tasks**:
  1. In [`miser/client.py`](miser/client.py), add support for model fallback chains:
     - Configure fallback model candidates in `.env` (`MISER_FALLBACK_MODELS=...`) or via `/model primary,fallback`.
     - When primary model returns HTTP 429 (rate/quota limit) or 503, automatically fall back to the backup model and notify the user.
  2. Implement an optional dual-model "Architect / Editor" mode:
     - High-level reasoning / planning handled by a reasoning model.
     - Fast, exact diff editing handled by a lightweight flash model.
- **Verification**: Add unit tests in `tests/test_client.py` mocking a 429 error and verifying seamless fallback to the secondary model.

### Phase 5: End-to-End Evaluation & Golden Tasks Benchmark
- **Objective**: Prove zero-regression, end-to-end bug fixing on Python and JavaScript fixtures.
- **Tasks**:
  1. Run the synthetic evaluation fixture suite:
     ```bash
     python3 -m miser evaluate --demo python
     ```
  2. Verify that the Python discount bug is solved with passing tests in <= 4 model calls and < 6,000 provider tokens.
  3. Benchmark before-and-after token consumption and record receipts in `docs/benchmark-results.md`.

---

## 4. Rules of Engagement & Constraints

1. **Documentation Integrity**: Preserve all existing docstrings, comments, and licensing headers.
2. **Never Hardcode Model Outputs**: Real LLM calls must be made via `ModelClient.complete()`; never fake or mock model completions in live interactive sessions.
3. **No Secret Leaks**: Never print, log, or serialize API keys, virtual keys, or tokens.
4. **Exact Edit Integrity**: Never silently bypass hash checks, test file boundaries, or sensitive path restrictions.
5. **Standard-Library-First**: Avoid adding heavyweight external dependencies unless strictly necessary.

---

## 5. Definition of Done

A phase is complete ONLY when:
1. `python3 -m unittest discover -s tests -q` passes 100% with zero regressions.
2. Real-world interactive session (`python3 -m miser chat`) functions smoothly with streaming, clean diffs, and exact accounting.
3. Relevant documentation and tests are updated.

