# MISER — current handover and next implementation

Updated 2026-11-10. Continue the existing project; do not rebuild the UI again or
repeat already-completed phases. Read `memory.md` for session history and the linked
evidence. Treat historical benchmark statements as recorded observations, not current
provider availability or proof of security/model reliability.

## Start here

- Repository: `/home/aman-kumar-sharma/Desktop/fresh-code`.
- Implementation baseline is `c167faa` on main, clean before this increment.
  This increment is uncommitted; preserve source/tests/docs and do not reset or clean.
- User files `cat.txt` and `config.json`: do not read, delete, overwrite
  or stage them merely because the user showed a MISER task involving a cat file.
  Implement the capability using temporary fixtures instead.
- Latest observed full suite: **447 tests in 32.424s, OK** (charcoal/activity).
  Its baseline was 446 in 28.176s; final focused UI/terminal/PTY run: 86/17.639s OK.
  Previous file-workflow full suite: 446/25.650s OK. This increment
  reproduced 430 in 24.859s; focused verification passed 235 in 21.928s. Reproduce
  a baseline before the next implementation, then red regression → focused → full.
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
- Default catalog is 20 tools. Inspect/research profiles expose 9/12 tools and
  reject edits/tests/commands at dispatch. Coding retains all 20 by default.
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

The user showed a 130-second unsuccessful delete/create task. The recorded run
had 55.635s in baseline tests and 71.533s across six model events; exact failed tool
errors/arguments were not retained. File deletion was unsupported then. It is now
implemented with a smaller dedicated workflow, but the original user's files were
not changed and that real-provider task has not been rerun.

## Implemented next increment: guarded deletion and file mode

Use `/files on` after launching/restarting the actual Textual CLI. It exposes seven
tools: zoom, read_many, write_file, edit, edit_batch, delete_file, ask_user, with a
shorter instruction prompt. It has no architect, commands, automatic tests, web/MCP
or todos. Mutations are constrained in dispatch to .txt/.md/.rst, excluding
requirements* and CMakeLists.txt; sensitive/test/path protections still apply.
Read-only inspect/research routing is not upgraded to write access. Results are
edited_unverified. `/files off` restores normal routing; `/checks required` restores
verification separately if manual was previously selected. New sessions remain auto
with required checks. File extensions do not prove edits irrelevant to application tests.

Deletion requires prior safe read/current version and a distinct fresh approval,
even when ordinary edit confirmation is off. No approve-all, headless auto-approval
or shell workaround. Private recovery copies and original path/mode/version manifests
are fsynced under `.miser/deleted/` before unlink; model paths cannot access them.
Content/identity and cancellation are rechecked after staging. Backups survive undo
and may remain after failed attempts; a backup is not proof deletion completed.
Live undo restores bytes/mode and refuses external replacements. Resume does not
reconstruct undo. ACLs, ownership, extended attributes and crash atomicity are not
claimed preserved. Final filesystem races remain; this is not an OS sandbox.

Shared deletion diffs handle empty/no-final-newline files and original-name display;
Git applicability is tested. WorkingMemory drops deleted versions across compaction
and clears the tombstone when a file is recreated. The default catalog/audit is now
20 tools, explicitly keeping delete_file outside parallel read-only batches.

See `docs/file-operations.md`, `tests/test_file_operations.py` and native regression
coverage in `tests/test_textual_app.py`. Actual native CLI PTY at 120×36, provider
simulated/live calls trapped: cancel/no writes, fresh approval without approve-all,
delete/create in three requests, zero tests, unverified result, undo bytes/mode,
clean exit. Scratch reproduction is /tmp/miser-files-pty.py (may not survive).

Local raw UTF-8/4 instruction/schema estimates: coding 775/1,910 (20 tools), files
239/783 (7 tools). Dynamic context/framing omitted; not billing or live latency.

## Current UI/activity follow-up

Theme is shared warm charcoal (#141414), with neutral surfaces and restrained
cyan/steel accents. Persistent ACTIVITY rail shows actual model/tool/test/approval
stages at narrow widths. Ordinary questions emit request lifecycle events too.
This does not expose private thinking or add model calls. Provider-supported brief
reasoning summaries would need a separate explicitly supported client callback and
labelled collapsible UI; that feature is not implemented. See docs/terminal-ui.md
and docs/ui/charcoal-*.png for actual simulated-provider CLI captures.

The user also requested removal of token/tool-use limits. This remains pending;
do not say limits were removed. Design optional host spending/step quotas separately
from finite context windows, cancellation, process cleanup, command approvals and
file protections. Avoid infinite retry loops or changing golden evaluation limits.

## Next implementation queue

1. Carefully invalidated verification selection/cache: source, tests, command/config
   and environment changes must invalidate. Unknown state cannot be called cached
   passing; no silent manual-policy switch. Required remains default for coding.
2. Measure representative task/429/cancellation behavior with correct usage labels.
   Live tests are optional; use gemini/gemini-3.5-flash-lite if run and label them real.
   Do not promise a fixed response time or treat simulated call counts as live gains.
3. Explicit host recovery retention/cleanup policy. Never let model tools erase
   backups or automatically replay untrusted recovery manifests. Assess crash and
   filesystem races separately from the existing live-session undo proof.
4. Remaining read_many compaction, ledger durability, full conversation resume,
   live MCP, browser verification and budgeted delegated workers are separate work.

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

Recorded for the last code increment: baseline 430/24.859s OK; broad focused
235/21.928s OK; full 446/25.650s OK. First full attempt failed two assertions
(catalog count and command-prefix collision); both were corrected without dropping
checks. See docs/file-operations.md for red regressions and observed outputs.
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
