# Golden-task benchmark results

This file records **measured** results only. A number that was not produced by a run
whose receipt is on disk does not appear here.

## Golden task

| Field | Value |
| --- | --- |
| Fixture | `examples/python_bug` (percentage-discount bug), `examples/javascript_bug` equivalent |
| Acceptance | `python3 -m unittest discover -s .` / `node --test`, run by the host after edits |
| Task prompt | "Fix the percentage discount calculation. Preserve tests and public API." |
| Command | `python3 -m miser evaluate --demo python` (add `--repeats N`, `--out DIR`) |
| Pass condition | tests pass, `model_calls <= 4`, provider `total_tokens < 6000`, usage complete |
| Budget per attempt | 12,000 tokens, 8 steps, fresh fixture copy |
| Caching | gateway caching must be disabled for a cold measurement |

The thresholds live in `miser/evaluation.py` (`GOLDEN_LIMITS`) and are asserted per run
in `report.json` under `runs[].golden`; `summary.golden_tasks_passed` counts the runs that
meet **all** of solved, metered, call-limited, and token-limited.

## Recorded attempts

| Date | Model | Run directory | Solved | Model calls | Provider tokens | Golden | Notes |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 2026-11-08 | `gemini/gemini-3.5-flash` (configured) | `runs/golden-python-check` | no | 0 | 0 | fail | Bifrost was not listening on `localhost:8080`: the run stopped at `model_error` with `usage_complete=false`, so no token or success claim is possible. |

The blocked attempt is recorded rather than hidden: the fixture copy, ledger, and
`report.json` remain on disk, and the run spent zero provider tokens because the request
never reached a provider.

## Tavily candidate evidence: one live call (2026-11-08)

This is a single live call, executed through the real code path
(`miser.verification.EvidenceSearch.verify_claim`) — not a benchmark and not repeated.
It records what the provider actually returned, including what it did **not** return.

| Field | Observed value |
| --- | --- |
| Endpoint | `https://api.tavily.com/search` (default; `TAVILY_API_URL` unset) |
| Claim | "subprocess.run raises CalledProcessError when check is true and the command exits with a non-zero status" |
| Version scope | `3.11` |
| Domains | `docs.python.org` |
| Request parameters | `max_results: 3`, `search_depth: basic`, `include_answer/include_raw_content: false` |
| Wall time (client) | 2.845 s (`elapsed_seconds: 2.844` in the ledger) |
| Ledger event | `kind="search"`, `status="candidates"` |
| Verdict | `unverified` (3 candidates, no confirmed review) |
| Provider-reported usage | **none** — the response has no `usage` key, so `api_usage` is `null` |
| Published dates | **none** — no `published_date` per result, so `published_at` is `null` |

Top-level response keys were `answer`, `follow_up_questions`, `images`, `query`,
`request_id`, `response_time`, `results`; per-result keys were `content`, `id`,
`raw_content`, `score`, `title`, `url`. `response_time` was `0.0`.

All three candidates resolved to the **same page** under different anchors:

| URL | Score | Excerpt |
| --- | --- | --- |
| `.../subprocess.html#subprocess.Popen.kill` | 0.8361405 | 1,126 chars |
| `.../subprocess.html#subprocess.Popen.pid` | 0.8361405 | 1,126 chars |
| `.../subprocess.html#subprocess.CompletedProcess` | 0.8361405 | 1,126 chars |

Two limitations this measurement exposes, both of which the product must not hide:

1. **Candidate count overstates distinct evidence.** Three results were one document.
   A card that says "3 sources" is misleading; the count should be of distinct pages.
2. **Version scope is not honoured by the provider.** The query scoped the claim to Python
   3.11, but the served page was the Python 3.15.2 documentation. The `version` field
   stays `unverified` rather than being promoted on a page that does not match the scope.

The evidence card is kept for inspection at `/tmp/miser-tavily-card.json` (temporary, not
committed). No API key value was written to any file or log.

## Live smoke run (2026-11-09) — one task, not a benchmark

Single end-to-end run through the real CLI and a real provider route. It is recorded
here because the numbers are measured, but one run with one model is not a benchmark
and is not comparable to the golden limits above.

| Field | Value |
| --- | --- |
| Command | `python3 -m miser smoke --language python --model gemini/gemini-3.5-flash-lite --out runs/smoke-phase12-20261109` |
| Fixture | `examples/python_bug` (copied by the smoke command) |
| Status | `tests_passed` |
| Model | `gemini/gemini-3.5-flash-lite` |
| Model calls | 4 |
| Tool calls | 6 |
| Failed model requests | 0 |
| Provider tokens | 8,663 in / 285 out / 8,948 total |
| Acceptance runs | 2 |
| Compactions / fallbacks | 0 / 0 |
| Ledger | `runs/smoke-phase12-20261109/result/ledger.json` |

Prompt component estimates from the same receipt (local estimates, **not** billing):
instructions 1,752; state 1,693; history 1,637; tool definitions 4,972; tool context
1,046. Tool definitions are the largest single block, which matters for any later
context work.

## Before / after token consumption

Not yet recorded. "Before" must be a real run of the same task and model with the same
acceptance command and caching disabled — for example `python3 -m miser run` with
compaction disabled and the PageRank map unused, versus the default configuration.
Fabricating the comparison from estimates (tool-context diagnostics are explicitly not
billing) would violate the project's accounting rule, so this table stays empty until a
live gateway is available.

## Reproducing

```bash
python3 -m miser doctor                     # configuration only, no secrets printed
python3 -m miser smoke --language python    # connectivity, real tokens
python3 -m miser evaluate --demo python --out runs/golden-python
python3 -m miser receipt runs/golden-python/python-1/ledger.json
```

`report.json` in the run directory holds the per-run receipt, the graded thresholds, and
failed-run spending; nothing here is reconstructed after the fact.
