# Lightweight file operations and guarded deletion

For small text-file tasks, restart MISER and select the session-local file mode:

```text
/files on
Delete note.txt and create new.txt with a short essay
```

Deletion opens a fresh approval dialog. Review it and explicitly approve or reject;
there is no approve-all deletion. `/undo` restores tracked live-session changes.
Return to normal coding with `/files off`; use `/checks required` too if you had
previously selected manual checks. `/status` shows the mode. New sessions start
with normal routing and required coding checks.

## What makes this mode lighter

The host advertises seven tools: zoom, read_many, write_file, edit, edit_batch,
delete_file and ask_user. A shorter instruction prompt directs use of known paths
and batches instead of redundant searches or planning. There are no command, test,
web, MCP or todo tools and no architect call. This is an opt-in chat mode, not a
new default for coding or a blanket automatic test exemption.

Mutations are limited in dispatch to .txt, .md and .rst paths. requirements* and
CMakeLists.txt names are excluded, along with all existing sensitive/test/path
protections. Other file types require normal mode. Read-only inspect/research
requests retain their own restricted profiles even when file mode is selected.
Extensions do not prove a file is irrelevant to application behavior. Completed
file changes are labelled **edited_unverified / tests not run**, never tests_passed.

Local size observations from the current code (UTF-8 bytes / 4 estimates):

| Profile | Tools | Instructions estimate | Schemas estimate |
| --- | ---: | ---: | ---: |
| Coding | 20 | 775 | 1,910 |
| Files | 7 | 239 | 783 |

These omit task/state/history/framing and are not provider tokens, money or a
latency benchmark. The tested delete/create workflow uses three **simulated**
requests: read version, delete/create batch, final reply. It runs zero acceptance
tests. Real providers may choose more calls or experience HTTP 429 delays. No
successful live speedup or fixed wall-clock completion time is claimed.

## Deletion contract

The new delete_file tool is available to coding and file workflows, not read-only
profiles or parallel read-only batches. It requires a prior safe read and matching
current version. It refuses directories/nonregular files, stale data, unsafe paths,
symlinks, sensitive files and acceptance-test paths. A separate fresh host approval
is required even when ordinary edit confirmation is off; headless/default API
callers without an approval callback refuse it.

Before unlinking, MISER writes and fsyncs a private recovery copy and JSON manifest
under `.miser/deleted/`. The manifest contains original relative path, mode and
version. Backup files use private permissions and no-follow directory-relative
access. They cannot be listed or read through model workspace tools. Content and
file identity are rechecked after staging; cancellation before unlink leaves the
source intact. The shell allowlist and metacharacter rejection are unchanged:
there is no rm tool or command workaround.

Recovery copies intentionally remain, including after undo and sometimes after a
canceled/failed attempt. A backup alone is not proof that deletion completed. They
contain file contents; keep them private. Retention/cleanup is a future host policy.
The manifest/raw copy permit manual recovery, but MISER does not automatically load
or trust them on resume. Existing /undo is live-session state; resume restores
metrics, not in-memory undo/conversation history.

Live undo restores original bytes, CRLF/no-final-newline state and permission bits,
and refuses external replacements. Created-then-deleted files revert to absence;
mode metadata is preserved across delete/recreate tasks and cleared after undo.
ACLs, ownership and extended attributes are not claimed preserved. Deletion diffs
identify the original filename instead of /dev/null, include mode headers and
represent empty/no-final-newline files; regression patches pass git apply --check.

Separate delete/create tool operations are **not atomic together**. A later failure
can leave the earlier deletion applied; retained recovery and /undo are available.
Content/identity checks narrow races but final filesystem syscalls still have the
previously documented TOCTOU boundary. App guards are not an OS sandbox. Recoverable
deletion currently requires POSIX; Windows and power-loss behavior are unverified.

## Verification

Baseline before implementation:

```text
set -o pipefail; .venv/bin/python -m unittest discover -s tests -q
Ran 430 tests in 24.859s
OK
```

New regressions failed before implementation. The first full run after the initial
implementation ran 444 tests in 25.771s and failed two checks: the catalog assertion
still expected 19, and the proposed /mode command collided with /model completion.
The catalog assertion now requires 20 and includes delete_file in the explicit
non-read-only set; its exhaustive mutation batching check is retained. The new
command is /files, preserving the old /model completion behavior. No existing
assertion was deleted, skipped or weakened to make that run pass.

Additional red checks caught deleted-file labels showing /dev/null and invalid
patches for empty/no-final-newline files. Original-file labels and shared deletion
patch construction fix these cases; Git applicability is asserted, not inferred.

```text
PYTHONPATH=tests .venv/bin/python -m unittest test_file_operations -q
Ran 14 tests in 0.053s — OK

PYTHONPATH=tests .venv/bin/python -m unittest test_file_operations test_audit test_tui_app test_textual_app test_terminal test_agent test_capabilities test_latency test_workspace test_execution test_ui_redesign test_textual_pty -q
Ran 234 tests in 22.488s — OK

.venv/bin/python /tmp/miser-files-pty.py
Actual native CLI PTY: /files on, fresh deletion approval without approve-all, cancellation/no writes, delete+create, three simulated model calls, zero tests, unverified result, undo bytes/mode, clean exit: OK
```

The separate native CLI PTY run used a temporary workspace at 120×36. Only the
provider was simulated; live calls were trapped, while actual filesystem operations,
version passing, approval keys, cancellation, receipts and undo ran through the real
CLI/backend. It did not modify the user's cat/config files. The scratch script may
not survive; repository native/backend regressions are in test_file_operations.py
and test_textual_app.py. No new OS screenshot or live-provider success is claimed.

A final consistency review added a red regression for WorkingMemory: deletion had
left the old version in durable breadcrumbs. Successful delete now records a
tombstone/removes that version across compaction; recreation clears it. Refused
operations do not clear the previous version. This supplements the earlier diffs
and undo regressions.

Final verification after the memory consistency regression:

```text
PYTHONPATH=tests .venv/bin/python -m unittest test_file_operations test_audit test_tui_app test_textual_app test_terminal test_agent test_capabilities test_latency test_workspace test_execution test_ui_redesign test_textual_pty -q
Ran 235 tests in 21.928s
OK

set -o pipefail; .venv/bin/python -m unittest discover -s tests -q
Ran 446 tests in 25.650s
OK
```

Final count is baseline 430 plus 15 file/backend regressions and one native approval
regression. Core -S help, chat help, diff whitespace and reference/example exclusion
checks passed. No new dependencies, commits, pushes, reference edits, user-file edits
or golden-threshold/benchmark changes. Documentation records earlier failed runs
as failures; no provider calls or live performance results were invented.
