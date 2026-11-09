# MISER

A coding agent that spends context carefully and records the bill. Early working foundation, not a benchmark-winning claim.

Python 3.11+ runs the core CLI with **no required third-party dependencies**. The
full-screen interface uses Rich when installed (`pip install 'miser-agent[tui]'`) and falls
back to the line interface otherwise. JavaScript demos require Node.js.

## Interactive application

Run `python3 -m miser` to open a full-screen coding terminal in the current directory:
a centered welcome with MISER branding and a composer card, followed by a structured
conversation with scrollable history, a persistent input area, real tool/model progress,
and an honest summary per task. The terminal is repainted in place on the alternate
screen; output does not accumulate as shell lines. `/help` lists commands; Tab discovers
commands.

```text
  MISER  gemini/gemini-3.5-flash                              680 tok · 1 task
────────────────────────────────────────────────────────────────────────────

  ▌ fix the percentage discount calculation.

  ⏺ miser · gemini/gemini-3.5-flash
    The formula multiplies instead of subtracting the discount.
    ✔ read   pricing.py · 0.0s
    ✔ edit   pricing.py
    ✔ acceptance tests passed

  ✔ tests passed  ·  0.8s
    680 provider tokens (600 in / 80 out)
  pricing.py  +1 −1
    ...
  ▌  Ask anything…
  tab complete · PgUp history · ctrl+d exit
```

Each task starts fresh model context, retains workspace edits, and saves a receipt and
patch. Use Enter to submit, Ctrl+J (or Alt+Enter) for a newline, Tab to complete commands,
Up/Down for persistent history, PgUp/PgDn to scroll, Ctrl+C to interrupt, and Ctrl+D to
exit. `/confirm on` reviews each edit with `y`/`n`/`a`/`d`; `/clear` returns to the welcome
screen. `--no-tui` forces the line interface. `--resume` restores session metrics, and
`--exec 'TASK'` (repeatable) runs prompts non-interactively. `--no-stream` disables live
streaming. See [terminal UI](docs/terminal-ui.md) for the layout, keybindings, fallback
rules, streaming semantics, and remaining limitations.

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
python3 -m unittest discover -s tests -v
```

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
| Atomic multi-file edits and standard unified-diff patches | Any text file; all-or-nothing transaction |
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

Use trusted repositories in a disposable environment. Common sensitive paths, traversal, symlinks, and conventional test-file edits are blocked by context tools, but this is **not an OS sandbox or comprehensive secret scanner**. Test commands execute repository code with normal user permissions; a malicious project can bypass file-access restrictions. The model cannot choose arbitrary shell commands. Edits require a unique exact match and a current file hash. Tool text is bounded, and test subprocess groups are terminated on timeout.

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
