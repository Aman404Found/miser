# MISER — current handover and next implementation

Updated 2026-11-10. Continue the existing project; do not rebuild the UI again or
repeat already-completed phases. Read `memory.md` for session history and the linked
evidence. Treat historical benchmark statements as recorded observations, not current
provider availability or proof of security/model reliability.

## Start here

- Repository: `/home/aman-kumar-sharma/Desktop/fresh-code`.
- HEAD remains `6898ab5` on master. Substantial later work is **uncommitted**, including
  new untracked source/tests/docs. Preserve it; do not reset, clean or overwrite it.
- User files `cat.txt` and `config.json` are untracked: do not read, delete, overwrite
  or stage them merely because the user showed a MISER task involving a cat file.
  Implement the capability using temporary fixtures instead.
- Latest observed full suite: **430 tests in 81.431s, OK**. This handover update
  changes documentation only; the suite was not rerun for it. Reproduce a baseline
  before the next implementation, then red regression → focused run → full suite.
- Python 3.12.3 here; requires-python >=3.11. Core dependencies remain empty. Optional
  `tui` uses Textual >=8.2.8,<9; optional `ui-test` supplies development-only pyte.
- Prepared `.venv`: Textual 8.2.8, Rich 15.0.0, pyte 0.8.2. System `python3` has no
  Textual. Launch from the project, using the correct interpreter:

```bash
.venv/bin/python -m miser chat . --tui
```

Or activate `.venv` first, then use `python3 -m miser chat . --tui`. Restart a running
MISER process to load code changes. Missing Textual selects the line interface unless
`--tui` explicitly requires the native application; the startup warning now prints
the complete project launch command. Do not install globally or auto-execute some
workspace's `.venv` to hide the interpreter difference.

## What is implemented

- Genuine Textual application at `miser/tui/textual_app.py`, selected by the actual
  interactive CLI: native layout, scrollable Markdown conversation, multiline
  composer, responsive sidebar, streaming, tool/test activity, diff and approval
  modals, cancellation and guarded multiline prompt history. Old Rich row UI files
  remain for legacy tests; there is no interactive CLI route to them.
- Existing real backend remains `miser/terminal.py`, `agent.py`, `client.py`,
  `tools.py`, `workspace.py`, `execution.py`, `ledger.py`. No demo provider in production.
- Default catalog is 19 tools. Inspect/research profiles expose 9/12 tools and
  reject edits/tests/commands at dispatch. Coding retains all 19 by default.
- Explicit bounded file reads and exact previous-message recall are local: no
  model, shell or acceptance tests. Live recent history includes local and agent
  turns, bounded to six pairs; three pairs enter model context. `--resume` restores
  metrics, **not full conversation**. Host-managed project facts are separate;
  MISER does not automatically read this development log as project memory.
- HTTP MCP read-only subset is already implemented: explicit external host config,
  allowlists, fresh invocation approvals, bounded untrusted output. No stdio/process
  servers, live MCP/Meko interoperability or successful live MCP model run verified.
- Parallel read-only tool calls and model streaming already exist. Do not propose
  them as missing. Parallel local reads are not proven faster; provider caching
  improvements and live end-to-end latency gains are not established.
- `/timing` and route/check-policy diagnostics report latest-prompt host durations.
  Model wait includes retries; tool sums overlap under parallel/nested work. Test
  duration is not counted twice through the run_tests wrapper. Missing durations
  and unfinished requests are explicit. Billing/count fields are unchanged;
  local estimates and timing are not provider billing.

## Test policy and the latest user complaint

Default `/checks required` runs coding baseline and post-edit acceptance checks.
A failed baseline supplies context; it does not prohibit continuing. Greetings,
ordinary questions, local reads/recall and inspect/research do not run those checks.

New `/checks manual` is an **explicit, session-local host choice**: skip automatic
baseline/post-edit checks and the optional architect; omit/refuse run_tests.
Edited tasks finish `edited_unverified`, displayed as “Edited · tests not run”.
It can leave code unverified; it is not an automatic text-only exemption. `/run`
and freshly approved commands remain explicit host test actions. `/checks required`
restores the default; new sessions always start required. File/version/approval/
command guards remain active. Do not let model output change this policy.

The user showed a 130-second unsuccessful delete/create essay task. The on-disk
`runs/session-d1203faa7bd1/ledger.json` reports baseline **55.635s**, six model events
summing **71.533s**, budget_exhausted and failed apply_patch/run_command events.
The screenshot shows HTTP 429 retry. That ledger does **not** retain exact failed
arguments/error text; do not invent those details. Source independently confirms
file deletion is unsupported. Native UI now displays actual bounded tool errors;
model instructions explicitly forbid trying shell deletion workarounds.

The user's exact delete/create request remains unresolved. Neither user cat file
was changed by this implementation. Manual checks remove automatic test overhead
only when selected; they do not solve unsupported deletion or provider throttling.

## Next implementation: guarded deletion

This is the immediate capability gap. Implement it without relaxing shell policy.
Inspect Workspace tracking, ToolRunner previews/dispatch, agent schemas, Terminal
compute_diff/session aggregation/undo, and native approval handling before coding.

Acceptance contract for a first increment:

1. A dedicated, bounded file-deletion operation; no arbitrary shell, recursive
   directory deletion or rm allowlist addition. Preserve sensitive/test-file guards.
2. Prior safe read and exact current version required. Reject missing/nonregular
   files, stale versions, traversal, symlinks and unsafe paths before mutation.
   Preserve rechecks and document the residual syscall race honestly.
3. Fresh explicit deletion approval, including when normal edit approvals are off;
   no approve-all deletion, model-controlled approval or headless auto-approval.
4. Accurate deletion diff and receipt/status. Keep enough original content/metadata
   for safe `/undo`; restore only when doing so cannot overwrite external changes.
   Handle empty files, modes, line endings, created-then-deleted files and session
   aggregation across task workspaces. Do not turn an unrelated missing file into
   an assumed authorized deletion.
5. Cover rejection, cancellation, concurrent changes, undo conflicts, partial/mixed
   failures and backup recovery. Define delete/create partial-failure behavior
   honestly; do not claim multi-file crash atomicity.
6. Unittest regressions fail before and pass after. Exercise the actual native CLI
   with a clearly simulated provider and real temporary filesystem operations.
   Update catalog/docs only after observing the new count and test results.

## After deletion

1. Reduce file-task round trips/tool schemas. Use direct supplied paths and bounded
   multi-reads where appropriate; avoid unnecessary search/planning. Any small-file
   profile must enforce its allowed operations and paths in dispatch, not rely on
   a model promise or silently treat code edits as verified documentation changes.
2. Design verification selection/cache with complete invalidation of relevant
   source, tests, command/config and environment inputs. Unknown state must not be
   labelled cached passing. Do not silently switch users into manual mode.
3. Measure a small deterministic task matrix: local read, question, new text file,
   delete/create, actual bug fix, failed tests, 429/recovery and cancellation.
   Compare calls, host durations and provider usage separately. Live tests optional;
   if run, use `gemini/gemini-3.5-flash-lite` and label them real.
4. Full conversation resume, live MCP interoperability, browser/UI verification and
   budgeted delegated workers remain separate future work; do not claim parity.

Safety work must not be displaced by cosmetic/features work: unresolved DNS/private
network pinning and filesystem TOCTOU are the highest-risk audit boundaries. Also
open: read_many compaction can lose paths/versions, power-loss ledger durability,
injection resistance and escaped-process/other-OS cleanup. See `docs/audit-report.md`.
App-level guards are not an OS sandbox.

## Verification and evidence

```bash
set -o pipefail; .venv/bin/python -m unittest discover -s tests -q
PYTHONPATH=tests .venv/bin/python -m unittest test_latency test_execution test_workspace test_terminal -q
python3 -S -m miser --help
.venv/bin/python -m miser chat --help
git diff --check
```

Recorded for the last code increment: baseline 417/89.225s OK; targeted diagnostics
16/1.149s OK; broad focused integration 166/79.541s OK; full 430/81.431s OK.
Do not present these as checks rerun by the next agent.

- `tests/test_latency.py`: ten timing/manual-policy regressions.
- `tests/test_textual_app.py`: native widgets/backend/launch/approval/error coverage.
- `tests/test_textual_pty.py`: actual CLI PTY with simulated provider and real failing/
  passing acceptance tests, edits, cancellation, resize and exit.
- Separate manual-mode actual CLI PTY at 120×36: real temporary file, zero tests,
  two simulated provider calls, unverified outcome/timing visible, clean exit.
  Scratch script `/tmp/miser-manual-pty.py` may not survive; evidence summary is in
  `docs/terminal-ui.md`. Do not depend on scratch files for future tests.
- Native captures in `docs/ui/native-*.png` are actual decoded PTY cells with
  simulated-provider labels, not OS screenshots or successful live-model runs.
- Golden limits remain unchanged and unmet in recorded runs: solved Python/JS
  fixtures used five calls and about 15k provider tokens versus four/6k limits.
  Do not alter thresholds, numbers or ignored runs evidence to manufacture success.

## Hard rules

- MISER branding only. `opencode/` and `aider/` are reference repositories: never
  modify, test, format, stage or package their contents; do not copy substantial code.
- No model-controlled arbitrary shell; retain token-prefix allowlists, metacharacter
  rejection, shell=False and fresh per-invocation approvals. Parentheses rejection
  is intentional; do not loosen it for python -c.
- Never print `.env*` contents or secrets. Loading configuration for a test is fine.
- No new required runtime dependencies. Use unittest, not pytest. Preserve unrelated
  changes and existing source protections. No commits unless asked; no push, force
  push, history rewrite or destructive cleanup.
- This host cannot bind listeners; mocked web transport and simulated providers are
  intentional. Restricted anonymous socketpair wakeups are handled by the native
  app's capability-gated timer. Do not add live-listener tests or suppress failures.
- Do not delete/skip tests, weaken existing assertions, swallow errors or add lint/
  type suppressions to obtain a green suite. Run red → focused → full verification.
- For the next code phase, do the work through reviewable implementation and actual
  checks. Finish by updating memory/docs with observed results and open limitations.
