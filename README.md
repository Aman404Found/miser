# MISER

A coding agent that spends context carefully and records the bill. Early working foundation, not a benchmark-winning claim.

Python 3.11+ runs the core CLI with **no required third-party dependencies**. The
full-screen interface uses optional Textual (`pip install 'miser-agent[tui]'`).
Without it, the CLI uses its line interface. JavaScript demos require Node.js.

## Interactive application

The native Textual application has a scrollable conversation, persistent multiline
composer, Markdown responses, real tool/test progress, a responsive session sidebar,
and modal edit/command approvals. It uses the existing MISER backend and receipts.

Launch using the prepared project environment:

```bash
.venv/bin/python -m miser chat . --tui
```

To keep using `python3`, first run `source .venv/bin/activate` in the project.
System Python without Textual uses the line interface; `--tui` refuses that fallback.

For a fresh checkout, install the optional interface with
`python3 -m pip install -e '.[tui]'` in your virtual environment. `--tui` requires
Textual and an interactive terminal; it fails clearly rather than silently launching
the legacy UI. Without that flag, TTY detection selects Textual when available;
`--no-tui`, `--exec`, pipes, `NO_COLOR` or `MISER_PLAIN` select the line interface.

Enter submits; Ctrl+J / Alt+Enter inserts a newline. Tab completes commands/paths,
Ctrl+P / Ctrl+N navigates prompt history, PgUp / PgDn scrolls conversation, F2 reviews
diffs, Ctrl+C cancels, and Ctrl+D exits safely. Native approval buttons are keyboard
and mouse accessible. Only an explicit **Approve all edits** disables later edit
prompts; commands and MCP tools still require fresh approval. `/confirm on` restores
edit prompts. `/clear` clears visible history without undoing files.

The UI now uses warm charcoal surfaces and muted cyan/blue accents. A persistent
ACTIVITY rail shows real request/tool/test/approval stages above the composer,
including at narrow widths. This is execution status, not private model reasoning;
provider reasoning-summary streaming is not currently implemented.

Each chat prompt now shows its selected route and test policy. A compact timing
summary separates model-request waits, acceptance checks and other tool sums;
`/timing` repeats the latest diagnostics without model calls. Parallel/nested work
can overlap, so category sums are not a breakdown that adds up to elapsed wall time.
Timing is visibility, not a measured speedup. For lightweight edits, explicitly
choose `/checks manual` to skip automatic acceptance commands; edited results are
labelled **unverified**. `/checks required` restores the default baseline/post-edit
checks. Path/version/approval guards and command allowlists stay active.

For lightweight text-file workflows, use `/files on`: seven tools, a shorter prompt,
no architect or automatic tests, and explicit **unverified** results. Changes are
limited to .txt/.md/.rst paths with sensitive/test/config-name guards. `delete_file`
requires a prior read/current version, a fresh approval and a private recovery copy;
no shell deletion is enabled. `/undo` supports tracked deletion and refuses external
replacements. Separate delete/create calls are not atomic. Return with `/files off`
and `/checks required` for normal verified coding. See [file operations and evidence](docs/file-operations.md).

`--resume` restores session metrics, not full conversation. `--exec 'TASK'`
(repeatable) preserves non-interactive automation; `--no-stream` disables streaming.
See [terminal UI](docs/terminal-ui.md) for actual CLI captures, verification and limits.

Explicit file-display requests run locally, without model calls or acceptance tests:
`read README.md`, `read Readme.md file and print first line`, or
`show first 20 lines of "project notes.txt"`. Reads retain workspace path/symlink/
sensitive-file guards, allow 1–120 lines and cap displayed text at 14,000 characters.
An exact filename wins; case-insensitive fallback requires one unique match in the
specified parent directory.

Repository questions such as `Explain miser/ledger.py` now use a read-only model
loop that reads actual source. Local inspection exposes 9 tools, web research 12,
and coding 20. Inspection/research skip acceptance tests and architect calls and
refuse edits, subprocess commands and tests at dispatch. Coding retains acceptance
verification and fresh command approval. Profile inference is a language heuristic;
the CLI can enforce an explicit read-only profile:

```bash
python3 -m miser run . 'Explain miser/ledger.py' --profile inspect --model 'provider/model-id'
python3 -m miser run . 'Look up official documentation for pathlib' --profile research --model 'provider/model-id'
```

`--test-command` remains required for the coding profile. These two read-only
examples call a real model when run and spend provider tokens; no live cost or
latency improvement is claimed from the smaller schemas alone.

The new `ask_user` tool can pause an active terminal/TUI task for a short question
with up to five choices or a free-text answer. Enter a choice number or type an
answer; the same task then continues with that answer. Escape in the TUI leaves the
question unanswered; Ctrl+C interrupts. Questions cannot be batched with edits or
other preplanned calls. At most three questions are allowed per task. Headless,
piped and `--exec` sessions stop with `needs_input` and show the question rather
than blocking or guessing. Rerun such a task with the missing detail supplied.
Clarification events store response presence and option count, not raw answers.

Project knowledge now persists across tasks and MISER sessions in the same repository.
Save facts explicitly; MISER does not automatically learn instructions from files or
model replies:

```text
/remember Core CLI uses the Python standard library
/remember --path pyproject.toml Core CLI requires Python 3.11 or later
/memory
/forget FACT_ID
/memory off
/memory on
/memory clear
```

The CLI equivalents need no model: `python3 -m miser memory . list`,
`python3 -m miser memory . add 'Core CLI uses the standard library'`, and
`python3 -m miser memory . forget FACT_ID`. Add a source link with `--path PATH`
after the fact text. Linked facts are excluded from context when source contents
change, disappear, become symlinks or cannot be safely read; review them with
`/memory`, then forget/re-save if needed.

Limits: 20 facts, 400 characters each; at most 8 whole facts and 3,000 serialized
UTF-8 bytes enter a task's context, ranked by simple keyword overlap and recency.
There is no context block when the store is absent/disabled/empty. Facts enter as
untrusted historical data, never system instructions; they can be wrong or stale.
The host saves/removes them; model tools cannot modify the store. Known configured
credentials and credential assignments are refused, but this is not a complete
secret scanner or a model-injection guarantee. Do not save secrets.

The ignored `.miser/project-knowledge.json` store uses private files, POSIX no-follow
directory-relative access, a host-writer lock, atomic replacement and file/directory
fsync. Storage is local to that repository path; copying it into another repository
is refused. POSIX access/locking is required for this feature; Windows behavior is
not verified. `chat --no-memory` and `run --no-memory` bypass loading completely,
including a corrupt store. Corruption otherwise fails closed and requires explicit
clear/recovery. This project store is separate from the development log `memory.md`.

Recent conversation now includes local reads, informational replies, greetings and
coding/inspection tasks in the same live session. Asking `what was my previous
message?` returns the latest submitted message locally, without a model call.
Slash commands are excluded. History retains at most six pairs / 12,000 serialized
UTF-8 bytes, with each message bounded to 1,500 UTF-8 bytes plus a truncation marker;
the latest three pairs enter model context. This history is session-local and is
not reconstructed by `--resume` or the separate project-facts store.

Explicit requests such as `i want you to read 4 lines from Readme.md and then print
here` also use the guarded local route, with no model or acceptance-test overhead.
This applies to permitted text files generally: for example `show first 2 lines of
app.py`, `read data.json`, or `read "project notes.txt"`. It is not README-specific.
Binary, sensitive and unsafe paths remain refused; local display is bounded.
Writes still use the model tool loop, checked versions/unique edits and acceptance
verification. Batched reads/edits reduce avoidable round trips, but no universal
read/write speedup or provider-cache improvement has been measured.
Model replies already stream by default; use `--no-stream` only when needed.
The native TUI uses Textual layout, input, scrolling and Markdown widgets rather
than flattening responses into manually repainted rows. Streamed source updates one
response widget per model request. Code highlighting, tables and links use native
rendering; links are inspected inside MISER rather than opened automatically.
Diff reviews retain raw patches separately from styled display. Actual CLI PTY tests
exercise the backend with simulated provider replies and real acceptance commands;
these are not live-model performance measurements.

External tools are opt-in: `chat . --mcp-config /outside/project/mcp.json` loads a
host-controlled HTTP MCP configuration. Only allowlisted, host-classified read-only
tools are supported, with fresh approval for every external call. `/mcp` lists
aliases; `/mcp list SERVER` discovers tools. Headless calls are refused. See the
[MCP setup and limitations](docs/mcp.md); no live service integration is verified.

Configure resilience and a two-model workflow in the session:

```text
/model gemini/gemini-3.5-flash,openai/gpt-5-mini   # editor plus 429/503 fallback chain
/architect gemini/gemini-3.5-pro                   # planner; editor still makes every edit
/confirm on                                        # review each file's diff before writing
```

For a disposable demo with tests already configured:

```bash
python3 -m miser chat --demo python
```

Type `Fix the percentage discount calculation`, then review `/diff` and `/receipt`.
The host runs acceptance checks automatically after an edit batch, without another
model request. This allows verification even if the next model request would exceed
the token budget. A failed test result is fed back to the next step.

```bash
python3 -m miser --help
python3 -m miser doctor
python3 -m miser demo --language python
python3 -m miser demo --language javascript
.venv/bin/python -m unittest discover -s tests -v
```

The full test suite requires the optional `tui` and development `ui-test` extras.
The demos copy small, deliberately buggy fixtures into `runs/`, apply a **scripted** fix, and run actual tests before and after. They make no LLM or Tavily calls and are not evidence of token savings. Original examples stay buggy so demos are repeatable.

## Explore any language

```bash
python3 -m miser inspect examples/javascript_bug
python3 -m miser inspect examples/javascript_bug --file pricing.js --level 2
python3 -m miser inspect examples/python_bug --file pricing.py --level 1 --symbol discounted_price
```

| Capability | Current support |
|---|---|
| Terminal interface | full-screen welcome + conversation, fixed composer/footer, scrolling, streamed Markdown, tool activity, reviewable diffs; line fallback |
| List, literal search, focused reads, delta recall, exact edits | UTF-8 text files across languages |
| Multi-file edits and standard unified-diff patches | Validate and stage before writing; atomic per file, best-effort rollback across files |
| Function/class outlines and symbol reads | Python AST; JS/TS/JSX/TSX structure via regex |
| Repository map | PageRank over identifier definitions/references (approximate graph) |
| Possible symbol references | Literal search approximation across languages |
| Long-session context | Compaction at 75% of budget; breadcrumb keeps versions and test status |
| Model resilience | Fallback chain on HTTP 429/503; optional architect/editor mode |
| Acceptance checks | A fixed command chosen by the user: Python, Node, build tools, etc. |
| Live official-documentation discovery | Tavily search; explicitly unverified evidence candidates |

HTML/CSS edits are supported as text; visual correctness requires a meaningful browser/build acceptance command supplied by the user. The JS/TS outline is a regex approximation, not a parser, and the repository map is a reference graph rather than a resolved call graph.

## Connect a real model

For Google AI Studio, start Bifrost with `npx -y @maximhq/bifrost`,
open `http://localhost:8080`, and add the Gemini provider in Model Providers.
Enter your API key in the local gateway UI, never in source code or chat.
Select a model enabled for your key and set `MISER_MODEL` to its
`gemini/<model-id>` identifier. Keep caching disabled for evaluation.

Once configured, run `python3 -m miser smoke --model 'gemini/<model-id>'`.
This makes real API calls, copies the Python fixture to a new run directory,
and asks the model to fix it with an approximate 12,000-token budget and eight-step
limit. Use `--language javascript` for the second fixture. Original fixtures
remain unchanged. The receipt is under the printed run directory; this small
smoke test establishes connectivity and behavior, not comparative efficiency.

Start and configure Bifrost separately, with a provider and model that support tool calls. Disable gateway response caching for the first evaluations. Keep provider keys in the gateway, not this repository.

```bash
export BIFROST_URL=http://localhost:8080/openai
export MISER_MODEL='provider/your-configured-model'
# Set BIFROST_VIRTUAL_KEY or BIFROST_API_KEY only if your gateway needs them.
# Run on a disposable copy: MISER edits the supplied repository in place.
python3 -m miser run /path/to/disposable/repo 'Fix percentage discount calculation' \
  --test-command 'python3 -m unittest discover -s .'
# For a JavaScript project, use its acceptance command, e.g. --test-command 'node --test'.
```

The host runs the acceptance command before the first model call. It then bounds history to four complete tool turns, caps steps/test runs/search attempts, compacts older turns when the estimated prompt reaches 75% of the budget, and stops after a patch passes the configured tests. Failed/incomplete runs retain their patches and receipt for inspection. It cannot undo other edits automatically.

Model usage comes from gateway `usage` fields. Missing usage stops the run. The token budget uses an approximate preflight check, so one call can exceed it; it is not a provider-enforced spending cap. Token estimates for tool outputs are separate diagnostics and never added to model totals. Neither API credits nor dollar prices are invented.

```bash
python3 -m miser receipt runs/<run-id>/ledger.json
export TAVILY_API_KEY='your-key'
python3 -m miser verify --claim 'A specific API accepts a specific argument' \
  --version 'installed-version' --domain docs.example.org
```

`verify` discovers sources for one explicit claim. Add `--judge-model 'gemini/<model-id>'`
for an optional provisional model verdict: supported, contradicted, or insufficient evidence.
The review uses search excerpts and requires exact source URLs, excerpt quotes, and version
anchors. Invalid citations cause abstention. Review tokens appear in the same ledger.
Quote validation does not establish semantic correctness; these verdicts require review.
It does **not** yet extract claims from arbitrary answers or calculate a validated freshness
score. A checked date is not a publication date. Evidence cards carry an applicable version
and invalidation condition; automatic dependency-change invalidation is pending.

## Execution boundaries

Use trusted repositories in a disposable environment. Common sensitive paths, traversal, symlinks, and conventional test-file edits are blocked by context tools, but this is **not an OS sandbox or comprehensive secret scanner**. Test commands execute repository code with normal user permissions; a malicious project can bypass file-access restrictions. The model cannot choose arbitrary shell commands. Exact edits require a unique match and a current file hash; unified diffs check the read snapshot and use hunk positions to disambiguate repeated text. Writes are rechecked before replacement, but concurrent processes can still race app-level path checks. Batches stage contents and backups first; commit failures attempt rollback and explicitly report incomplete rollback with retained backup paths. They are not crash-atomic across files. Tool text is bounded, and subprocess groups are terminated on timeout or interruption. Background command jobs belong to one task and are cleaned up when it ends. Every command invocation needs fresh approval; piped stdin is not an approval channel.

Web URL guards block literal private addresses (including legacy numeric IPv4 forms),
but do not resolve and pin DNS addresses. Private DNS destinations and rebinding
remain open risks. Untrusted-content labels are prompt policy, not proof that a model
will ignore injected instructions. Configured gateway/search credentials are refused
in web inputs and redacted from web transport errors; this is not a general secret scanner.

## Next milestones

Run `python3 -m miser evaluate --demo python` after gateway setup to grade the golden
task (tests pass, ≤4 model calls, <6,000 provider tokens). Use `--language`/`--repeats 3`
for the broader fixture sweep; each attempt has an approximate 12,000-token budget and
eight-step limit. This spends API tokens. Each run uses a fresh copy and preserves its
ledger, and results are recorded in [benchmark results](docs/benchmark-results.md).
The generated `report.json` includes failed-run spending in tokens per solved
task and leaves that metric unknown when usage is incomplete. Transport
failures stop the suite to avoid repeated failed requests. These synthetic
fixtures are connectivity checks; real-repository baseline evaluation is pending.

1. Smoke-test the real Bifrost/model and Tavily integrations with configured credentials.
2. Resolve the Python caller/import graph so `blast_radius` reports callers rather than literal references.
3. Add claim extraction and source-supported verdicts, with a transparent freshness rubric and abstention.
4. Run pinned real-repository tasks against a real OSS-agent baseline; publish outcomes and all spend.

See [methodology](docs/methodology.md) and [implementation status](docs/implementation-status.md). The original master plan is retained; the status document records the agreed multi-language direction and deferred features.
