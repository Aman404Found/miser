# MISER — working memory

Living log of what has been done, what is verified, and what is next.
Update this file at the end of every work session. Newest entries at the top of
"Session log"; keep "Current state" accurate rather than appending forever.

Last updated: 2026-11-09 (session 3)

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

- Python 3.12.3, `requires-python >=3.11`, no runtime dependencies.
- `miser/` ≈ 27 files / ~5.8k LOC.
- **Tests: 200 passing** — `python3 -m unittest discover -s tests -q` (exit 0, ~9.7s).
- **Tools: 14** — `repo_map`, `list_files`, `find_files`, `search`, `zoom`, `recall`,
  `read_many`, `write_file`, `edit`, `edit_batch`, `apply_patch`, `blast_radius`,
  `run_tests`, `verify_claim`.
- Roadmap phases 1–4 of `HANDOVER_PROMPT.md` were already implemented before this
  session; `docs/agent-roadmap.md` Phases 1 and 2 are now implemented too.

### Environment blockers

- **Git is broken**: `.git/` contains only `info/exclude` — no `HEAD`, no `objects`.
  `git status` → `fatal: not a git repository`. Nothing is committed; no commit, diff,
  or log is possible until the repo is re-initialised or restored.
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
- **Git is broken** (see above); nothing from Phase 1/2 or later is committed.

---

## Session log

### 2026-11-09 — truncation status, live gateway probe, first real smoke run

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

1. Decide on git: re-initialise the repo (`git init` + `.gitignore` review) or restore
   it from a copy. Needed before any commit or diff exists.
2. ~~Confirm the gateway works end-to-end~~ — done: smoke run passed, but the
   Phase 1/2 *baseline* numbers remain unavailable.
3. Phase 3 — supervised execution (allowlist, approval, real exit status, background +
   stop, no shell, reject metacharacters). **Needs explicit user approval** because it
   touches the no-arbitrary-shell rule.
4. Phase 4 — `write_todos` re-emitted each step.
5. Phase 5 — `web_search` / `fetch_url` with the untrusted-content contract.
6. Phase 6 — concurrent read-only tools; summarising compaction.
7. Phase 7 — evaluation harness producing a dated `docs/benchmark-results.md` table.

---

## Useful commands

```bash
python3 -m unittest discover -s tests -q          # full suite
python3 -m unittest tests.test_workspace -q       # focused
python3 -m miser                                   # TUI
python3 -m miser --no-tui                          # line interface
```
