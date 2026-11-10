# MISER audit — 2026-11-09

Baseline: clean `master` at `6898ab5`, **249 tests passed**. Final audited working
tree: **290 tests passed**, including **41 new unittest checks**. Changes are
uncommitted; nothing was pushed. No live model calls, benchmark runs, socket
listeners, reference-repository operations, or dependency installations were made.
Final Git check: still `master` at `6898ab5`, 17 modified tracked files and two
new files (`tests/test_audit.py`, this report). `git diff --check` is clean;
`examples/` and `pyproject.toml` have no diff.

The suite is green, but this is **not a security certification**. DNS destinations
are not pinned, same-user processes can race path checks, and prompt labels do not
prove model resistance to injected instructions. Those boundaries remain open.

## 1. Baseline: exact commands and output

`git status --short` returned no output, exit 0.

`git log --oneline -5` returned, exit 0:

```text
6898ab5 Record the Phase 7 golden-task runs and their limits honestly
1070968 Run independent read-only tools in parallel and compact with structured digests
0822a11 Report a text-only final reply as answered, not incomplete
0e8d718 Record the live web search and fetch check for Phase 5
ef73374 Add web_search and fetch_url with the untrusted-content contract
```

`set -o pipefail; python3 -m unittest discover -s tests -q` returned, exit 0:

```text
----------------------------------------------------------------------
Ran 249 tests in 7.388s

OK
```

`git ls-files | grep -E '^(opencode|aider)/'` returned no output, exit 1
(the expected no-match result).

`git ls-files | grep -iE '\.env|secret|credential'` returned, exit 0:

```text
.env.example
```

No environment-file contents were displayed.

`python3 -m miser --help` returned, exit 0:

```text
usage: miser [-h]
             {doctor,chat,smoke,evaluate,inspect,run,receipt,demo,verify} ...

Focused coding context, explicit budgets, honest receipts.

positional arguments:
  {doctor,chat,smoke,evaluate,inspect,run,receipt,demo,verify}
    doctor              Check local prerequisites without displaying keys
    chat                Open the interactive coding terminal
    smoke               Live model test on a disposable demo copy (uses API
                        tokens)
    evaluate            Live fixture suite with usage report (uses API tokens)
    inspect             Explore a repository without a model
    run                 Run the real model-backed coding agent
    receipt             Read a run's recorded bill
    demo                Scripted offline tool demo; not an LLM benchmark
    verify              Discover evidence for one explicit claim (candidate
                        stage)

options:
  -h, --help            show this help message and exit
```

`python3 -m miser evaluate --help` returned, exit 0:

```text
usage: miser evaluate [-h] [--model MODEL] [--repeats {1,2,3,4,5,6,7,8,9,10}]
                      [--language {python,javascript}]
                      [--demo {python,javascript}]
                      [--token-budget TOKEN_BUDGET] [--max-steps MAX_STEPS]
                      [--out OUT]

options:
  -h, --help            show this help message and exit
  --model MODEL
  --repeats {1,2,3,4,5,6,7,8,9,10}
  --language {python,javascript}
  --demo {python,javascript}
                        Run the golden fixture task with call/token thresholds
  --token-budget TOKEN_BUDGET
  --max-steps MAX_STEPS
  --out OUT
```

`python3 --version` returned `Python 3.12.3`, exit 0. `rg` was unavailable
(exit 127); subsequent discovery used tracked-file lists and bounded source reads.
The baseline count matched, so there were no pre-existing changed tests to explain.

## 2. Findings

Locations refer to the final source tree. Evidence names below are methods in
`tests/test_audit.py` unless another file or command is named. P0 describes a
security/data-loss boundary; exposure can still require an approved command or a
concurrent process. Application guards are not an OS sandbox.

| Severity | File:line | What was wrong | Evidence | Status |
| --- | --- | --- | --- | --- |
| P0 | `miser/workspace.py:716` | A partial write to file 2 left it truncated; rollback omitted the failing file and could falsely claim complete recovery. | `test_failed_partial_batch_write_preserves_all_three_files`, `test_batch_rollback_failure_is_reported_and_backup_retained`; existing write-failure regression | fixed: stage new files and backups; replace per file; report incomplete rollback and retain backups |
| P0 | `miser/workspace.py:608` | External changes between the version check and write were overwritten. | `test_edit_rechecks_version_after_building_replacement` | fixed for reproduced interval by rechecking; final syscall race remains below |
| P0 | `miser/workspace.py:565` | Creation could overwrite a file appearing after `exists()`; failed creation left an untracked partial file. | `test_create_does_not_overwrite_a_file_appearing_after_check`, `test_failed_new_file_write_removes_its_partial_file` | fixed: exclusive creation and partial-file cleanup |
| P0 | `miser/execution.py:83` | `/tmp/git status` passed basename matching and selected that executable after approval. | `test_allowlisted_basename_cannot_select_an_arbitrary_executable_path` | fixed: reject executable paths; allowlist unchanged |
| P0 | `miser/web.py:62` | Legacy numeric IPv4 names bypassed private-address checks and denote loopback. | `test_legacy_numeric_private_addresses_are_refused_before_transport`; local `inet_aton` repro | fixed: parse legacy numeric forms without DNS or sockets |
| P0 | `miser/web.py:34` | Configured credentials could be sent in a fetch URL or reflected into search errors. | `test_fetch_refuses_a_configured_credential_in_url_before_transport`, `test_web_errors_do_not_echo_configured_credentials` | fixed for configured Tavily/Bifrost credentials; not a general secret scanner |
| P1 | `miser/workspace.py:644` | Later edits in the same-file batch skipped their supplied version checks. | `test_every_edit_in_same_file_batch_must_have_the_base_version` | fixed: every operation validates the pre-batch version |
| P1 | `miser/workspace.py:823` | A prior read was enough to patch externally changed content; no snapshot-version check. | `test_patch_refuses_external_changes_since_read` | fixed |
| P1 | `miser/workspace.py:823` | After an earlier insertion, a later hunk could edit the wrong repeated line. | `test_later_patch_hunk_uses_original_coordinates_after_line_insertion` | fixed: account for preceding hunk line-count changes |
| P1 | `miser/workspace.py:106` | The no-final-newline marker changed both diff sides; application also forced a newline back in. | `test_patch_can_remove_only_the_new_side_final_newline` | fixed |
| P1 | `miser/workspace.py:271` | Universal-newline reading converted entire CRLF files to LF on edit. | `test_edit_preserves_crlf_and_executable_mode` | fixed; ordinary executable permission bits preserved |
| P1 | `miser/execution.py:177` | Direct calls to `run()` skipped validation performed by `invoke()`. | `test_run_validates_allowlist_even_when_called_directly` | fixed: validate at the execution boundary too |
| P1 | `miser/execution.py:142`, `miser/terminal.py:312` | Exact-argv approval was cached; piped stdin could act as approval input. | `test_each_command_invocation_needs_fresh_approval`, `test_non_tty_stdin_is_not_a_command_approval_channel` | fixed; line/TUI “always” UI removed |
| P1 | `miser/execution.py:124`, `miser/agent.py:289` | Global jobs crossed task/supervisor boundaries and survived agent completion. | `test_job_from_another_supervisor_cannot_be_read_or_stopped`, `test_agent_exit_closes_its_background_jobs` | fixed: task-owned jobs and final cleanup |
| P1 | `miser/execution.py:177`, `miser/tools.py:118` | Ctrl-C did not reap foreground children; TUI cancellation was not checked during waits. | `test_keyboard_interrupt_kills_foreground_process`, `test_acceptance_interrupt_reaps_child`, both `test_cancellation_is_checked_during_*` tests | fixed: cancellable waits and terminate/reap on interruption |
| P1 | `miser/execution.py:177`, `miser/tools.py:118` | A successful parent could leave live children, including when its PID no longer had a discoverable PGID. | `test_successful_foreground_command_does_not_leave_live_descendants` (real command and acceptance subprocesses) | fixed for descendants remaining in the POSIX group |
| P1 | `miser/agent.py:95`, `miser/agent.py:289` | Activity results followed completion order; success exited before observing all already-executed results. | `test_parallel_activity_results_are_delivered_in_model_order`, `test_success_observes_every_result_in_the_completed_batch` | fixed |
| P1 | `miser/tools.py:232` | An unsuccessful edit could retain a passing pre-edit test result, including after incomplete rollback. | `test_failed_edit_invalidates_pre_edit_acceptance_result` | fixed: invalidate before attempting mutation |
| P1 | `miser/ledger.py:72` | Non-object usage crashed before recording unknown spending. | `test_malformed_usage_still_records_unknown_spend` | fixed: record unknown usage, then stop with ValueError |
| P1 | `miser/ledger.py:91` | Tool-context totals accepted fields from unrelated event kinds. | `test_receipt_tool_context_ignores_unrelated_event_fields` | fixed; token-total reads also take the existing RLock |
| P1 | `miser/evaluation.py:48` | An unmetered response stopped one task but evaluation proceeded to another paid request. | `test_unmetered_model_response_stops_evaluation_with_partial_report` | fixed: stop and persist the partial report |
| P1 | `miser/agent.py:289` | Missing tool-argument fields raised KeyError instead of returning recoverable feedback. | `test_missing_tool_arguments_produces_recoverable_tool_message` | fixed |
| P1 | `miser/terminal.py:333` | Undo crashed on a deleted/otherwise inaccessible edited file. | `test_undo_missing_existing_file_reports_conflict_without_crashing`; existing session/undo tests | fixed: report conflict and retain undo state |
| P2 | `miser/agent.py:289` | Empty replies had no useful explanation. | `test_empty_reply_explains_incomplete_status` | fixed: small explanatory note, status unchanged |
| P1/P2 | six requested Markdown documents | Stale tool inventory/count, JSONL claim, unconditional atomicity, cached approval, unsupported reliability/zero-cost statements and injection-resistance claims. A “correct” 3.10 `read_text(newline=...)` claim conflicts with Python 3.12.3. | Source, recorded ledger comparison, `inspect.signature(Path.read_text)`, documentation diff | fixed wording; numerical benchmark results unchanged |
| P0 | `miser/web.py:62`, `miser/web.py:83` | Ordinary hostnames are not resolved/pinned; private DNS targets and rebinding remain possible. | URL-policy repro accepts arbitrary hostname and performs 0 DNS lookups; transport source | proposed, not fixed: a complete fix needs a pinned-address TLS/proxy transport or enforced network policy; a separate DNS precheck would still race |
| P0 | `miser/workspace.py:253`, `miser/workspace.py:271` | Path/symlink checks and filesystem operations are separate syscalls. | Source inspection; version-race regression covers the larger interval, not syscall atomicity | proposed, not fixed: portable app-level checks cannot establish an OS isolation boundary; descriptor-relative no-follow access and platform policy need separate work |
| P2 | `miser/agent.py:215` | `read_many` results can compact to “tool result dropped”, losing paths/versions. | `compact_digest` repro below | proposed; guards require rereading, but this harms context quality |
| P2 | `miser/ledger.py:34` | Snapshots use atomic replacement but no fsync; power-loss durability is not guaranteed. | Source; partial-temp-write test preserves previous valid JSON | proposed; no power-loss test or durability claim |

## 3. Changes made and covering tests

- Replaced direct edit writes with staged per-file replacement, pre-write version
  checks, prepared backups and honest rollback errors. Covered by the partial-write,
  rollback-failure and recheck tests listed above, plus `tests/test_workspace.py`.
- Made creation exclusive and removed partial creations on failure. Covered by the
  two `test_*new_file*`/creation-race regressions.
- Enforced same-file batch versions and patch read snapshots. Covered by
  `test_every_edit_in_same_file_batch_must_have_the_base_version` and
  `test_patch_refuses_external_changes_since_read`.
- Fixed multi-hunk offsets and side-specific final-newline handling. Covered by
  `test_later_patch_hunk_uses_original_coordinates_after_line_insertion` and
  `test_patch_can_remove_only_the_new_side_final_newline`.
- Preserved CRLF and file permission bits through edits. Covered by
  `test_edit_preserves_crlf_and_executable_mode`.
- Enforced program-name and direct-run validation without expanding prefixes or
  weakening metacharacter rejection. Covered by the path/direct-run regressions
  and `test_execution_prefix_and_metacharacter_boundaries`.
- Required fresh command approval, including line/TUI prompt changes and non-TTY
  refusal. Covered by the fresh-approval and non-TTY tests. The previous “always”
  test now asserts the explicitly requested fresh-approval behavior.
- Isolated task jobs and added process-group cleanup for success, interruption,
  cancellation and agent exit. Covered by the job, cancellation, interrupt and
  real-descendant regressions. Processes escaping their group are outside this guard.
- Buffered parallel activity into model order and consumed completed results before
  success exit. Covered by the order and complete-observation regressions.
- Invalidated acceptance state before mutations. Covered by
  `test_failed_edit_invalidates_pre_edit_acceptance_result`.
- Hardened malformed usage handling, locked token-total reads, and limited receipt
  summation to tool events. Covered by malformed-usage, concurrent-ledger and
  unrelated-event tests.
- Stopped evaluation on unknown usage with its report intact. Covered by
  `test_unmetered_model_response_stops_evaluation_with_partial_report`.
- Made missing arguments recoverable and empty replies explanatory. Covered by
  the missing-arguments and empty-reply regressions.
- Made undo preserve/report inaccessible-file conflicts and use checked writes.
  Covered by the new missing-file test and existing session-isolation/undo tests.
- Refused known credentials in web inputs, redacted transport errors, and blocked
  legacy numeric private IPv4. Covered by the credential and legacy-address tests.
- Corrected the six requested documents and tool descriptions to describe their
  actual boundaries. Evidence is code, tests and existing receipts; no benchmark
  thresholds, budgets, numerical benchmark results or evidence files were changed.

The existing write-failure test now injects failure at `os.replace`, the new commit
boundary, and still asserts rollback. No tests were deleted, skipped or weakened.
No architectural/formatting-only quality pass was undertaken.

## 4. Checks run and actual outcomes

Verification order was baseline → failing reproductions → focused tests → full
suite. Some intermediate runs failed and were corrected; these are not hidden.

| Command/check | Actual result |
| --- | --- |
| Initial `python3 -m unittest discover -s tests -p test_audit.py -q` | 16 tests, failures=11/errors=4; two fixture mocks were corrected, then failures=13/errors=2. This was an expected red regression run. |
| First broad `PYTHONPATH=tests python3 -m unittest test_audit test_workspace test_execution test_agent test_web test_evaluation test_request_diagnostics test_session_isolation test_terminal test_tui_app -q` | 176 tests, failures=1/errors=2. Found a new-test environment leak (CLI env loading) and an undo integration error; both corrected, no assertions relaxed. |
| Final `python3 -m unittest discover -s tests -p test_audit.py -q` | exit 0; `Ran 41 tests in 1.777s`, `OK` |
| Final focused command (same module list as above) | exit 0; `Ran 180 tests in 11.480s`, `OK` |
| Final `set -o pipefail; python3 -m unittest discover -s tests -q` | exit 0; `Ran 290 tests in 12.614s`, `OK` |
| `python3 -m unittest discover -s tests -p test_workspace.py -q` | exit 0; `Ran 23 tests in 0.036s`, `OK` (earlier focused check) |
| `python3 -m unittest discover -s tests -p test_execution.py -q` | exit 0; `Ran 8 tests in 0.318s`, `OK` (earlier focused check) |
| `python3 -S -m miser --help` | exit 0; same help text as baseline, with site packages disabled |
| `git diff --check` | exit 0; no output |
| `git diff --name-only -- examples pyproject.toml` | exit 0; no output |
| Repeated tracked reference/sensitive filename scans | reference paths empty; sensitive-name output only `.env.example` |

Exact final full-suite output:

```text
----------------------------------------------------------------------
Ran 290 tests in 12.614s

OK
```

The final audit tests were also run against a disposable archive of the pristine
baseline, without checking out or changing the working tree. Exact command:

```bash
python3 - <<'PY'
import io, shutil, subprocess, sys, tarfile, tempfile
from pathlib import Path
archive = subprocess.run(['git','archive','6898ab5','miser','tests','examples'], check=True, capture_output=True).stdout
with tempfile.TemporaryDirectory(prefix='miser-audit-baseline-') as tmp:
    with tarfile.open(fileobj=io.BytesIO(archive)) as bundle:
        bundle.extractall(tmp, filter='data')
    shutil.copyfile('tests/test_audit.py', Path(tmp)/'tests/test_audit.py')
    result = subprocess.run([sys.executable,'-m','unittest','discover','-s','tests','-p','test_audit.py','-q'], cwd=tmp, capture_output=True, text=True)
    Path('/tmp/miser-audit-baseline.log').write_text(result.stdout + result.stderr)
    print('Pristine 6898ab5 with final audit tests; unittest exit:', result.returncode)
    for line in result.stderr.splitlines():
        if line.startswith(('FAIL:', 'ERROR:', 'Ran ', 'FAILED ', 'OK')):
            print(line)
PY
```

The wrapper exited 0; the enclosed unittest exited **1**, as intended:

```text
Pristine 6898ab5 with final audit tests; unittest exit: 1
Ran 41 tests in 3.879s
FAILED (failures=32, errors=5)
```

There were 33 failing test methods (subtests account for the larger failure-entry
count); eight invariant checks already passed on the baseline. The detailed red
tracebacks were saved in `/tmp/miser-audit-baseline.log`. They use synthetic
credentials/providers and disposable fixture files, not benchmark evidence.

The dependency/tool inspection parsed `pyproject.toml`, AST-scanned only `miser/`,
and counted `SCHEMAS`. Exact output:

```text
requires-python: >=3.11
required runtime dependencies: []
optional dependencies: {'tui': ['rich>=13.7']}
tools: 18 unique: 18
non-stdlib import roots: ['rich']
```

Thus the **core CLI** has no required third-party runtime dependencies. Rich is an
existing optional TUI dependency, so “the entire full-screen app is stdlib-only”
would be false. No dependency/config changes were made. Python 3.11 execution and
wheel installation were not tested on this Python 3.12.3 host.

Additional boundary evidence:

- The prefix/metacharacter test covers `gitfoo`, env prefixes, newline/CR,
  semicolons, logical operators, pipes, backticks, substitutions and redirects.
  Globs are accepted as literal argv and never shell-expanded. Popen's default
  `shell=False` is retained; acceptance commands remain host-selected.
- All eight non-read-only tools are individually shown to disable agent parallel
  dispatch. Existing agent tests cover parsed read batches, malformed JSON,
  compaction thresholds, decision reinjection and ordered model messages/memory.
- The ledger stress check runs 60 writers through 12 workers: 120 persisted events,
  exactly 180 reported model tokens, and no contribution from unrelated kinds.
  Existing WebAccess reservation test grants exactly 5 of 12 concurrent attempts.
- The actual ledger is **JSON**, not JSONL. A failed partial temp write preserves
  the previous valid JSON snapshot; `finish()` synchronously calls `flush()`.
  That proves neither fsync durability nor a cross-process writer lock.
- Evaluation tests separately reject each golden condition, verify expensive
  solved tasks exit 1, preserve `examples/`, refuse existing output directories,
  reconcile receipts to ledgers, and persist unknown-usage partial reports.
  Timings are local wall-clock measurements, not model-token billing.
- Existing `test_session_isolation.py` covers fresh task success state, patch
  separation, external undo conflicts and cross-repository resume filtering. It
  did **not** cover the global command-job registry; the new job test does.
  UI width/unicode/key-routing tests passed; no real interactive visual review was
  performed. Arbitrary terminal Unicode/grapheme behavior is not exhaustively proved.

## 5. Recorded evidence and known-open items

The audit read existing reports/ledgers selectively and recomputed `receipt()`;
it did not run, fabricate or reconstruct benchmark attempts:

| Existing run | Status | Model calls | Provider-reported tokens | Complete usage | Receipt matches report |
| --- | --- | --- | --- | --- | --- |
| `golden-python-20261109a` | `budget_exhausted` | 4 | 11,098 | true | true |
| `golden-python-20261109b` | `tests_passed` | 5 | 15,000 | true | true |
| `golden-js-20261109a` | `tests_passed` | 5 | 14,937 | true | true |
| `golden-python-check` | `error` | 0 | 0 known | false | false: legacy receipt shape differs; not regenerated |

The solved attempts have the recorded costs of roughly 15k tokens / 5 calls, so
the **unchanged** `<=4 calls`, `<6000 tokens`, solved, complete-usage requirements
produce `golden_tasks_passed: 0`. These runs do not prove those limits mathematically
unreachable for every strategy/model. They do prove the measured runs missed them.

Additional existing evidence was found: smoke solve 8,948 tokens / 4 calls;
web session `session-e4d476853be7` 18,777 tokens / 4 model calls / 3 web calls,
legacy `incomplete` status; answered session `session-764157a062c5` 17,808 tokens /
7 calls. Provider invoices, current gateway availability, disabled caching and
historical UI behavior were not independently verified. Provider-reported usage
is not a dollar bill. Client retry/fallback subattempt spending also cannot be
established from final returned usage alone; no zero-cost retry claim is made.

Known-open boundaries:

1. **DNS/private networking:** URL checks do not resolve/pin DNS. A simulated
   policy repro accepted `https://private.audit.invalid/` and performed **0 DNS
   lookups**. Complete protection needs vetted pinned-resolution TLS/proxy behavior
   or external network restrictions, beyond a safe local allowlist tweak.
2. **Path TOCTOU and crash atomicity:** rechecks close the reproduced larger window,
   not the final syscall race. Same-user malicious processes, hardlinks/metadata,
   filesystem crashes and rollback failures are not an OS sandbox. File permission
   bits were tested; inode identity, ACLs, ownership and extended attributes were not.
3. **Sockets/live models:** no local-listener tests were attempted on this host.
   Web transports/providers in unit tests are simulated. Live model runs were
   optional and not performed. Redirect revalidation, size limits and budgets passed
   mocked-transport tests; real DNS/proxy behavior remains unverified.
4. **Parentheses:** `check_argv` deliberately lists `(` and `)` as metacharacters.
   `python3 -c "print(1)"` is also outside the default prefixes. Rejection is
   intentional under the current policy; neither boundary was loosened.
5. **Untrusted content:** labels and tool-role placement were verified. Ignoring
   injected instructions is a model-behavior claim that the suite does not prove.
   Known configured web credentials are guarded, but arbitrary secrets in source,
   returned pages, task text or subprocess output are not comprehensively detected.
6. **Compaction:** the current task is reinserted in state; the latest turn is kept
   as digests and decisions appear only after compaction. However, the direct repro
   `compact_digest(json.dumps({'reads':[{'path':'app.py','version':'v','text':'1: value = 1'}]}))`
   returned `{"tool": null, "digest": "tool result dropped after compaction"}`.
   No guarantee of retaining every latest result/path/version is justified.
7. **Process cleanup:** real POSIX same-group child cleanup was exercised. A process
   deliberately escaping its group, Windows descendant cleanup, network-call
   cancellation latency and SIGKILL of MISER itself remain outside that proof.
8. **Ledger durability:** atomic snapshots preserve the previous file on staged
   write failure; power-loss durability and multi-process writes remain unverified.
   A malformed usage event records zero *known* numeric tokens with
   `usage_known=false`; it does not represent zero-cost success.

No P0/P1 security guarantee is claimed for the open DNS and filesystem isolation
boundaries. They remain explicit risks rather than being “fixed” by a passing mock.

## 6. Recommended next work, ordered by risk reduction

1. Enforce filesystem/network/process isolation for untrusted repositories; design
   descriptor-relative no-follow file access and DNS-pinned transport with explicit
   TLS/redirect/proxy tests. These are the highest-risk open boundaries.
2. Add crash-recovery/durability work: fsync policy, recoverable multi-file journal,
   failure injection at replacement/cleanup boundaries, and documented metadata policy.
3. Make retry/fallback subattempts observable for accounting, and preserve uncertainty
   about any unmetered remote spend. Do not infer zero billing from HTTP failures.
4. Extend compaction digests for `read_many` and multi-file versions; measure whether
   rereads, dropped decisions and prompt size actually improve on long tasks.
5. Test model injection behavior with controlled simulated transport before live
   services; test real TTY cancellation, Unicode and resumed sessions on a host that
   supports the required integrations. Mock labels are insufficient evidence.
6. Add the missing cross-file/add-test/lint evaluation tasks, then measure cost with
   pinned models and comparable baselines. Keep current golden limits and historical
   numbers intact; any proposed threshold change needs a separate justified decision.
