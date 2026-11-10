# Native MISER terminal application

MISER's interactive CLI now launches a genuine Textual application. The earlier
redesign still flattened Rich renderables into console rows and managed its own
input/repaint loop; better Markdown and colors did not change that architecture.
The new application uses native widgets, layout, focus, scrolling and resize events.
The reference image guides hierarchy and restraint, not a promise of pixel-identical
browser effects. Terminal fonts and color capabilities still determine appearance.

## Launch and dependencies

This checkout has an installed optional UI in `.venv`:

```bash
.venv/bin/python -m miser chat . --tui
```

For a new environment, install `.[tui]`; development UI checks additionally require
`.[ui-test]`. Tested here: Python 3.12.3, Textual 8.2.8, Rich 15.0.0 and pyte 0.8.2.
The `tui` extra declares Textual >=8.2.8,<9 (and its transitive dependencies), replacing
Rich alone. `ui-test` supplies only the development terminal emulator. The core
`dependencies = []` and Python >=3.11 requirement are unchanged. Python 3.11 and
other platforms were not separately exercised.

`--tui` requires interactive stdin/stdout and Textual, and rejects `--exec`. It
reports a clear error if unavailable. Automatic selection uses Textual when both
streams are TTYs; missing Textual, `--no-tui`, `--exec`, pipes, `NO_COLOR` or
`MISER_PLAIN` select the line interface. Explicit `--tui` overrides the environment's
plain-mode preference. Non-interactive commands retain their existing implementation.
The old `miser/tui/app.py` remains for legacy regression compatibility; there is no
interactive CLI route or flag to it. Old Rich PTY captures are historical evidence.

## Interaction

| Control | Native application behavior |
| --- | --- |
| Enter | Submit prompt or slash command |
| Ctrl+J / Alt+Enter / supported Shift+Enter | Insert newline |
| Tab | Complete commands or guarded workspace paths |
| Arrows, Home, End | Native editor navigation |
| Ctrl+P / Ctrl+N | Previous/next saved prompt |
| PgUp / PgDn | Scroll conversation or open approval details |
| F2 | Review current diff |
| Ctrl+L | Focus composer |
| Ctrl+C | Cancel active task; clear draft when idle |
| Ctrl+D / Ctrl+Q | Cancel safely and exit after backend cleanup |
| Tab / Shift+Tab, Enter, mouse | Focus/activate native approval controls |
| Escape in a dialog | Reject approval or leave question unanswered |

The multiline composer grows to eight visual rows. Header, composer and footer
remain visible while conversation scrolls. At widths below 118 columns the sidebar
hides. Following output pauses when scrolling upward and resumes at the bottom or
on a new submission. Busy submissions do not start a second task or discard a draft.
`/clear` clears the visible transcript, not backend turn context or workspace edits.
`/diff` and F2 show collapsible syntax-highlighted patches; narrow result diffs start
collapsed. Approval diffs start expanded. Displayed numbers are **patch line numbers**,
not old/new source coordinates; unified hunk headers preserve source coordinates.

Edits have Reject, Approve and explicit Approve all edits controls. Reject is focused
initially. Approve all edits changes the existing session confirmation flag;
`/confirm on` restores per-edit prompts. Command and HTTP MCP approvals have no
approve-all option and prompt every invocation. `ask_user` uses a native question
modal and resumes the same backend loop. Headless refusal remains in the backend.

Prompt history uses bounded private JSON in `.miser/textual-history.json`, preserving
multiline prompts. Legacy line history is read only when no new file exists. POSIX
no-follow directory-relative access, regular-file checks and atomic private-file
replacement protect this host UI state. History contains submitted prompts; do not
enter credentials. It is separate from recent-turn model context and project facts.

## Presentation and backend integration

`miser/tui/textual_app.py` owns native widgets and presentation. The existing
`Terminal`, agent, model client, workspace, execution policy and ledger remain the
backend. A dedicated backend thread posts typed UI messages; widgets mutate only on
the UI thread. Modal callbacks wait on cancellation-aware events. No model, tool,
acceptance command, or provider usage is synthesized by production UI code.

Native Markdown renders headings, paragraphs, emphasis, ordered/unordered lists,
inline code, blockquotes, separators, tables and language-labelled highlighted code.
Tables/code can scroll within native widgets at narrow widths. Links display their
label; clicking shows the destination as data inside MISER, never opens a browser.
Original response/patch content remains separate from sanitized display. Each model
request has one Markdown widget; throttled updates replace its source and flush the
final text, rather than appending duplicate streamed fragments. The line interface
continues using its existing renderer.

Semantic cards distinguish user, assistant, local file/recall, activity, errors and
results. Running state reflects actual backend events. Status distinguishes known
usage from unknown/incomplete usage; completed request count excludes failed calls.
A regression found that failed informational requests omitted unknown-usage tracking;
that path now marks usage unknown instead of presenting zero-cost completion.
No rendering code adds model requests or changes budgets. Idle status updates are
cached. There is no measured provider-latency or token-saving claim from this work.

Cancellation remains cooperative: a blocked network request can wait for a callback
or timeout; remote charges may remain unknown. Application guards are not an OS
sandbox. This host also denies anonymous socketpair sends, breaking asyncio's usual
thread wakeups. `miser/tui/wakeup.py` probes that capability without binding a listener
and only on EPERM/EACCES adds a public-loop timer; normal hosts use normal wakeups.
The timer also lets Markdown executor shutdown complete on this restricted host.

## Verification and actual captures

Baseline before this rebuild:

```text
set -o pipefail; python3 -m unittest discover -s tests -q
Ran 399 tests in 21.118s
OK
```

Native regression coverage (real Terminal backend, scripted providers as specified):

```text
.venv/bin/python -m unittest discover -s tests -p test_textual_app.py -q
Ran 16 tests in 35.099s
OK

MISER_NATIVE_CAPTURE=/tmp/miser-native-captures .venv/bin/python -m unittest discover -s tests -p test_textual_pty.py -q
Ran 1 test in 8.019s
OK

PYTHONPATH=tests .venv/bin/python -m unittest test_terminal test_capabilities test_agent test_ui test_tui_app test_tui_screen test_recent_turns test_ui_redesign test_session_isolation test_execution test_mcp -q
Ran 202 tests in 12.877s
OK
```

The native CLI PTY test calls the actual `cli.main` selection path and native app;
only its provider is simulated, with a trap forbidding live ModelClient calls.
It exercises a greeting, streamed Markdown question, multiline editor, scrolling,
80×24 → 120×36 → 160×45 resize, real failing baseline unittest, version-checked edit,
Ctrl+C refusal with no write, fresh approval, actual passing acceptance test, receipts
and safe exit. Resize capture waits for the footer to reach the new terminal bottom.
Ledger assertions verify interrupted/tests_passed statuses and two successful coding
model events. Simulated usage and timings are not live model benchmarks.

Separately, an **unmodified** `.venv/bin/python -m miser chat TEMP --tui --no-memory
--model gemini/gemini-3.5-flash-lite` process was exercised in an 80×24 PTY without
provider patches: welcome, hello, guarded local file read, invalid-budget error and
Ctrl+D exit passed. Its ledger had one local-read event and zero model/test events.
It verifies the production launch and local routes, not live provider integration.

These PNGs were rendered from the actual CLI PTY's decoded terminal cells and visually
inspected; they are not design mockups or OS screenshots. Captions explicitly identify
the simulated provider. The final capture set was regenerated after resize timing was
corrected. The native app was inspected at all three requested widths and approval
controls remained visible at 80×24.

- [80×24 Markdown conversation](ui/native-conversation-80x24.png)
- [120×36 conversation and sidebar](ui/native-conversation-120x36.png)
- [160×45 conversation](ui/native-conversation-160x45.png)
- [80×24 edit approval](ui/native-approval-80x24.png)
- [160×45 completed task and receipt](ui/native-completed-160x45.png)

`tests/test_textual_app.py` separately checks native layout, incremental source,
local actions, ask_user, cancellation, actual CLI selection, fresh command/MCP
approval callbacks, explicit approve-all edits and re-enabling confirmation, link
inspection, literal diff filenames, multiline history and restricted-host wakeups.
Headless widget tests and old renderer tests are not substitutes for the CLI PTY run.

No successful live provider/gateway integration was verified in this rebuild.
An early fixture patched the wrong factory and attempted the unavailable local
gateway; the corrected fixture traps live calls. No live socket listener is required.
Universal emoji/grapheme shaping, other terminal emulators/OSes, desktop-terminal
mouse-copy behavior and aesthetic acceptance remain unverified. Use the line
interface when ordinary shell scrollback is preferred.

An initial full run passed 416 tests in 47.585s. A later full rerun, after stronger
resize assertions, exposed an existing process-test race:

```text
set -o pipefail; .venv/bin/python -m unittest discover -s tests -q
Ran 416 tests in 79.736s
FAILED (errors=1)
ProcessLookupError: /proc/PID/stat disappeared between exists() and read_text()
```

The cleanup probe now reads one snapshot and treats only FileNotFoundError or
ProcessLookupError as an already-exited process. Live sleeping/running descendants
still fail, zombies are non-live, and permission errors propagate. A deterministic
regression covers those distinctions; the previous assertion's ProcessLookupError
was reproduced with a patched disappearing process. No product cleanup assertion
was removed or skipped.

```text
PYTHONPATH=tests .venv/bin/python -m unittest test_audit.AuditTests.test_cleanup_probe_treats_exit_during_read_as_gone_but_live_process_as_live test_audit.AuditTests.test_successful_foreground_command_does_not_leave_live_descendants -q
Ran 2 tests in 0.160s
OK

PYTHONPATH=tests .venv/bin/python -m unittest test_audit test_textual_pty -q
Ran 43 tests in 9.610s
OK
```

Additional checks: `python3 -S -m miser --help` and `.venv/bin/python -m miser chat
--help` exited 0; `git diff --check` passed; `git diff --name-only -- opencode aider
examples` was empty. Parsed packaging confirms empty core dependencies, Python
>=3.11 and `miser*` only. No commits or pushes were made. Prior unrelated working-tree
changes and user files were preserved.

A subsequent full run found one PTY synchronization assumption (417 tests in
64.611s, FAILED with one failure): the approval title had painted while the native
diff was still rendering, so an immediate assertion did not yet see `return 2`.
The test now waits, within its existing deadline, for the actual patch and approval
controls rather than accepting the title as proof of a completed render. Assertions
about file contents, decisions, test outcomes and accounting are retained. The
revised targeted CLI PTY test passed: one test in 7.570s, OK.

Final verification after both synchronization fixes:

```text
PYTHONPATH=tests .venv/bin/python -m unittest test_audit test_textual_pty -q
Ran 43 tests in 11.612s
OK

set -o pipefail; .venv/bin/python -m unittest discover -s tests -q
Ran 417 tests in 72.571s
OK
```

Asyncio debug mode emitted slow-callback diagnostics on this constrained host;
they were not suppressed and the final suite exited 0. The final count is baseline
399 plus 16 native regressions, one CLI PTY test and one cleanup-probe regression.

## Routing and latency diagnostics (2026-11-10)

Chat now shows the host-selected route and verification policy before work, then a
compact host-timing summary after a completed task. `/timing` shows the latest
submitted prompt's diagnostics without calling a model or running tests. Native
Textual displays the same diagnostics and an actual baseline/acceptance-running
state. The default required test policy and all command/file guards remain unchanged; the
explicit manual policy below is opt-in. Timing itself adds no model requests.

Routes include local-read, local-recall, conversation, question, inspect, research
and coding. Only coding advertises baseline and post-edit acceptance checks. Unsafe
or ambiguous local reads still fail before printing file content or diagnostics.

Timing separates total wall time, summed model request waits (including client
retries), acceptance-command durations, and other tool duration sums. The run_tests
wrapper is excluded from tool sums because its tests event already measures the
command. Parallel tools and nested operations overlap; these categories are not a
partition of total time. Approval waits remain inside tools. Missing durations and
unfinished requests are labelled unknown. These are host timings, not billing or
provider compute time, and do not establish a speedup.

For coding/inspection/research/local reads, a `task_timing` ledger event persists
the summary. Receipt billing/count fields are unchanged. Ordinary conversational
answers retain their existing session-only accounting; their measured request wait
is available in `/timing`, not invented as a provider ledger event. Each submitted
prompt resets the diagnostics; greetings/questions never reuse another run's
ledger. Resuming metrics does not restore old timings.

If the full-screen UI appears to have disappeared, check the interpreter: this
checkout's Textual is installed in `.venv`, not the system Python. From the project:

```bash
source .venv/bin/activate
python3 -m miser chat . --tui
```

Or use `.venv/bin/python -m miser chat . --tui` directly. Missing-UI startup now
prints that complete command. No automatic execution of another environment or
system-wide dependency installation is introduced.

## Explicit manual verification for lightweight tasks

`/checks manual` selects a session-local host policy: skip the automatic baseline
and post-edit acceptance command, omit the run_tests tool, and skip the optional
architect. Guarded writes still use the existing path, sensitive-file, version,
uniqueness and approval checks. A completed reply after edits records
`edited_unverified` and displays **Edited · tests not run**, never tests_passed.
The UI marks checks skipped rather than retaining another task's green check.
Command allowlists and fresh approval still apply. `/run` is an explicit host test
action; manual policy does not prevent a user from authorizing a test command.

`/checks required` restores baseline and post-edit checks. Required remains the
default for every new session and for evaluation; no environment variable or model
tool changes the policy. `/status` shows the setting. Manual mode can also leave
code changes unverified, so use required mode for coding work. It is an explicit
tradeoff, not automatic affected-test selection or a security sandbox.

File deletion remains unsupported. Existing apply_patch only edits previously-read
files; it cannot create/delete them. write_file creates a new file. Command limits
were not expanded to provide rm or a workaround. The model instructions and patch
schema now state this limitation explicitly; native tool errors display the actual
bounded reason, rather than only a failure cross. A properly guarded deletion tool
with undo/approval coverage remains separate next work.

The reported slow run `runs/session-d1203faa7bd1/ledger.json` was read from disk:
status budget_exhausted, baseline 55.635s, six model events totalling 71.533s, and
failed apply_patch/run_command tool events. These events do not retain their error
text, so the precise failed arguments/errors cannot be established from that ledger.
The supplied screenshot shows HTTP 429 retry. No successful rerun, deletion, live
model speedup or completion of that user's task is claimed. User cat.txt/config.json
were left untouched.

Verification for the diagnostics/manual-policy increment:

```text
set -o pipefail; .venv/bin/python -m unittest discover -s tests -q
Baseline: Ran 417 tests in 89.225s — OK

PYTHONPATH=tests .venv/bin/python -m unittest test_latency test_textual_app.NativeApplicationTests.test_failed_tool_shows_reason_and_manual_checks_cannot_show_previous_green_status test_textual_app.NativeApplicationTests.test_native_activity_displays_route_timings_and_actual_test_running_state test_textual_app.NativeLaunchSelectionTests -q
Ran 16 tests in 1.149s — OK

PYTHONPATH=tests .venv/bin/python -m unittest test_latency test_terminal test_capabilities test_agent test_ui_redesign test_session_isolation test_local_reads test_recent_turns test_execution test_textual_app test_textual_pty -q
Ran 166 tests in 79.541s — OK

.venv/bin/python /tmp/miser-manual-pty.py
Actual native CLI PTY/manual policy: real file created, zero tests, 2 simulated provider calls, unverified status, timing visible, clean exit: OK

set -o pipefail; .venv/bin/python -m unittest discover -s tests -q
Final: Ran 430 tests in 81.431s — OK
```

The manual-mode PTY run used the actual CLI/native application at 120×36; only
provider responses were simulated, with live calls trapped. Existing required-mode
PTY tests still exercise failed/passed real acceptance commands. Regression tests
failed before feature implementation. An earlier focused run failed the existing
ambiguous-file/no-output assertion: route/timing output was moved after successful
local path validation, preserving that assertion. No checks were deleted or skipped.
System Python without Textual and project Python with Textual 8.2.8 were checked
separately; no system environment was changed. `git diff --check`, core `-S` help
and reference/example diff exclusion passed. No live latency benchmark was run.
