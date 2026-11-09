# MISER — working memory

Living log of what has been done, what is verified, and what is next.
Update this file at the end of every work session. Newest entries at the top of
"Session log"; keep "Current state" accurate rather than appending forever.

Last updated: 2026-11-09 (session 5)

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
- **Tests: 222 passing** — `python3 -m unittest discover -s tests -q` (exit 0, ~7.2s).
- **Tools: 16** — `repo_map`, `list_files`, `find_files`, `search`, `zoom`, `recall`,
  `read_many`, `write_file`, `edit`, `edit_batch`, `apply_patch`, `blast_radius`,
  `run_tests`, `verify_claim`, `run_command`, `write_todos`.
- `docs/agent-roadmap.md` Phases 1, 2, 3 and 4 are implemented and covered by tests.
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

1. ~~Decide on git~~ — done: re-initialised, `.gitignore` in place, `04f4b8b` committed.
2. ~~Confirm the gateway works end-to-end~~ — done: smoke run passed, but the
   Phase 1/2 *baseline* numbers remain unavailable.
3. ~~Phase 3 — supervised execution~~ — **done and tested** (8 new tests, 208 total).
   The arbitrary-shell rule is now enforced in code: allowlist prefixes, metacharacter
   rejection, `shell=False`, per-invocation approval, real exit status,
   background + stop. Headless runs refuse because there is no approval channel.
4. ~~Phase 4 — `write_todos` re-emitted each step~~ — **done and tested** (14 new
   tests, 222 total). Plan is re-injected every step, stale turns get a reminder,
   and both interfaces render one checklist per update. Not yet exercised by a live
   model-driven task.
5. Phase 5 — `web_search` / `fetch_url` with the untrusted-content contract.
6. Phase 6 — concurrent read-only tools; summarising compaction.
7. Phase 7 — evaluation harness producing a dated `docs/benchmark-results.md` table.

## What the user may need to do

- Nothing is blocked on the user for Phase 4. If a future task should run
  `ruff`/`mypy`, those binaries must actually be installed; the allowlist permits them
  but does not install them.
- Live model work should keep using `gemini/gemini-3.5-flash-lite`; the plain
  `gemini-3.5-flash` route is 429 for tool-bearing requests.

---

## Useful commands

```bash
python3 -m unittest discover -s tests -q          # full suite
python3 -m unittest tests.test_workspace -q       # focused
python3 -m miser                                   # TUI
python3 -m miser --no-tui                          # line interface
```
