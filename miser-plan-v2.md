# 🧊 MISER — Master Plan v2

> One combined hackathon project covering **Bifrost Track 01** (coding agent that gets the job done on the fewest tokens) and **Tavily Track 01** (stale-answer detector with per-claim freshness scores).
> Team: 2–3 people · Deadline: demo-ready in ~2–3 days · Demo style: terminal/CLI.
> Owner of doc: team lead. Update task statuses in place; do not silently re-scope.

---

## 1. The thesis (say it the same way every time)

> **"Ask any agent to fix a bug and it pays to read the world. MISER walks a graph, spends tokens like fuel, verifies its memory against today's live web, and hands you a receipt. Same bugs, a fraction of the tokens — and every claim in the patch carries a freshness score with a source."**

Three discipline pillars (this is the positioning, in order of importance):

1. **Least-privilege context** — code access is rationed, metered, priced: graph hops, zoom levels, ledger `recall` instead of re-reads.
2. **Evidence over memory** — the agent never trusts training-data knowledge the repo cannot corroborate; it spends tiny verified micro-checks (Tavily) instead of burning tokens on thrash or shipping stale APIs.
3. **Everything measured, nothing hidden** — receipts count *all* spend (radar included, useless fires included), per-category eval results, ablations, method published.

Framing to avoid (we get mistaken for the sponsor's own marketing otherwise): do **not** pitch "semantic caching / model routing / MCP Code Mode" as our contributions. Bifrost is our neutral referee (measurement + caching infrastructure), not our claim. Our contribution is the harness policy + tools + verifiability layer.

---

## 2. Locked decisions

| Decision | Choice |
| --- | --- |
| Track picks | Bifrost 01 × Tavily 01 (one combined build) |
| Structure | One repo, one CLI, one demo `miser` |
| Build strategy | Thin core agent from scratch (~600–800 lines) + tools packaged MCP-wrap-able so any OSS agent can wear them |
| Baselines | REAL product baseline (a popular OSS coding agent, same model through our Bifrost) — never a strawman on stage |
| Graph scope | Python-first (tree-sitter), JS/TS only if stretch hours appear |
| Task suite | 8 curated tasks from small real repos (pin by commit), ≤3 deliberately radar-relevant, labelled honestly |
| Stack | Python 3.11+ (typer + rich CLI, tavily-python, tree-sitter language pack, OpenAI-compatible client → Bifrost). Reversible only until end of Phase 1 |
| Fees/keys | No keys yet → free tiers: Google AI Studio (Gemini flash), Groq (llama-3.3-70b), Tavily (free tier). Same model for MISER and all baselines |
| Artifact demotions | `$0 replay` = governance footnote (config, not a feature). Waste taxonomy = stretch. Bifrost PR = roadmap issue only, no Go plugin attempt |
| Out of scope (deal-list) | Web UI, IDE extension, SWE-bench, multi-agent swarms, browser automation, multi-language graphs, offline reruns |

---

## 3. What changed from v1 (red-team corrections — all applied)

- ❌ Strawman baseline as the stage comparison → ✅ real OSS agent baseline + published method + ablations.
- ❌ Assumed 350 tok/verification → ✅ realistic 1–3k tok/search; radar spend counted in receipts, every fire logged incl. no-value fires.
- ❌ Graph = flagship differentiator → ✅ policy+budgets likely deliver most savings; graph gets an ablation to prove its share, and ships Python-first.
- ❌ Stale-API tasks unstated → ✅ at most 3 of 8 tasks radar-relevant, clearly labelled, per-category results reported.
- ❌ `$0 replay` as USP → ✅ demoted to footnote.
- ✅ NEW: standalone `miser verify` CLI so the Tavily-01 rubric is fully ticked by a dedicated artifact, not by vibes.
- ✅ NEW: ablation column — `OSS-agent baseline` (primary headline) vs `MISER-policy-only` vs `MISER-full`, plus internal-sanity `strawman`.

---

## 4. Architecture

```
miser CLI (python)
  agent loop: plan → act → verify → stop-on-green (budgets + retry cap 3)
  │
  ├── ALL model calls → Bifrost gateway :8080 (OpenAI-compatible drop-in /openai)
  │        • semantic cache plugin in DIRECT mode (dimension: 1 → no embedding provider needed)
  │        • usage tokens per response + x-bifrost-cache-hit headers + cost from catalog
  │        • free-tier provider(s) wired in UI config
  │
  ├── tools (each reports its own token cost into the ledger; each MCP-wrap-able)
  │        graph tools / read tools / verify tools / test tools → below
  │
  ├── Tavily radar (verify_claim, supply_chain) — hard cap 3 fires/task
  │
  └── ledger.json per run → receipt (itemized token bill) → eval reports
```

**Fairness rule (never break it):** same model, same Bifrost, same test verdicts for MISER and every baseline; only the harness differs. Tokens measured by Bifrost usage fields. All configs + methods published in `/docs`.

---

## 5. Tool arsenal (build list v2)

### Tier 1 — MUST ship (the demo set)

| Tool | Spec (one line) | Token math | Demo beat | Effort |
| --- | --- | --- | --- | --- |
| `recall` | Only file-read access path; returns last-read snapshot + line-delta since instead of re-reading | 2,000 tok → ~40 tok | naive reads same file 11×; MISER recalls deltas | XS |
| `zoom` | Progressive read: L0 signature+docstring (~20 tok) → L1 body (~200) → L2 window (~2k); agent must choose to zoom | "read 8 files" → "L0 everything, L1 four fns, L2 two windows" | meter visibly ticks up per zoom — the fuel dial | S |
| `blast_radius <symbol>` | Query Python graph: callers/importers/tests within N hops as compact tree | decision-quality context ≪ file dumps; also selects only impacted tests | edit → radius lights up → 3 of 47 tests run → catches regression naive missed | M |
| `mutation_probe` | After tests pass: mutate the fixed line → impacted tests must fail → patch proven load-bearing | 3–4 tiny runs | "naive passes too, until we mutate it" | S |
| `verify_claim` | Standalone CLI too (`miser verify <answer.md>`): claim extraction → staleness class → 1 Tavily micro-search per risky claim → per-claim verdict + source + date table | 1–3k tok/claim, capped | radar fires ONCE on purpose; ledger shows every fire incl. useless ones | M |
| `supply_chain` | Audit pinned deps (pyproject/package.json) vs live sources: stale versions + CVEs, per-dep freshness score | ~2–4k tok/audit | "1 CVE fixed in yesterday's patch" — T01 applied to a lockfile | S |
| `receipt` | Itemized bill: reads, zooms, radar spends, test runs, cache hits, retries; naive-vs-MISER comparator; agent itself queries budget ("82% spent — no re-reads") | — | the photograph judges take | S |

### Tier 2 — stretch (only with spare hours, in this order)

1. `what_changed` — semantic diff ("3 fns changed, 1 signature widened, 2 tests at risk") vs raw diff dumps.
2. `assumptions` — agent logs every assumption as `repo-evidence / verified-fresh / guess`; `guess` → radar check forced before edit.
3. JS/TS graph (second language via tree-sitter-typescript).
4. Waste-taxonomy post-mortem profiler (where token spend lives, per category).
5. `pattern_twin` — find a proven analogous in-repo implementation to copy shape from.
6. `miser brief <company>` easter egg (T02 = same claim engine, news mode).

### Design rules for every tool

- Reports its own token cost into the ledger (receipt is fed by tools as they run, not reconstructed later).
- MCP-wrap-able (stdio JSON) → packaged server means OpenCode/Goose/Claude Code can mount them: **"any agent can wear MISER"** — our portability USP.
- Degrades gracefully: `blast_radius` without graph → grep-based approximation, clearly labelled.

---

## 6. Rubric compliance map (pin in README + demo slide)

**Bifrost 01 artifact set:**
- `miser` coding agent CLI with measurable tokens-per-solved-task (Bifrost-metered), success rate, and the 4-config comparison (strawman internal / **OSS agent baseline primary** / MISER-policy-only / MISER-full).
- Tools: recall, zoom, blast_radius, receipt — the "least-privilege context" demo.

**Tavily 01 artifact set:**
- `miser verify` standalone CLI: any LLM answer in → claims out → flagged-stale ranked → re-verified live → per-claim freshness score + source + date. Works on ANY LLM output, independent of the agent.
- In-agent radar + `supply_chain` (lockfile freshness) as two client faces of the same engine.

Both maps get one slide each in the README — no judge can claim we half-ticked a rubric by accident.

---

## 7. Evaluation & fairness protocol

**Task suite (MVP = 8; stretch 10).**
- Source: small real repos (<3k LOC, with test suites), cloned & pinned by commit; 5 Python (graph-ready) + 3 whatever-installs-fastest.
- Task types: failing test / small bug / tiny feature. Acceptance = tests green.
- Each task card: repo, commit, bug summary, est. difficulty, radar-relevant flag (≤3 labelled radar-relevant).
- Seed script clones, installs, sets up venv so every agent runs in the identical env.

**Baselines (same tasks, same model, same Bifrost):**
1. `strawman` — naive dump-file agent (`--profile baseline`): internal sanity + waste data only, never the stage headline.
2. `oss-baseline` — one popular OSS coding agent, headless, routed through our Bifrost (the headline comparison).
3. `miser-policy` — our core + budgets/zoom/recall, graph disabled (ablation).
4. `miser-full` — everything on.

**Metrics per task (from Bifrost usage + headers):** input/output tokens, cache-hit rate, $ at catalog prices, success (tests green), retries, re-read count, radar fires (incl. no-value fires), wall time.
**Reporting rules:** medians across tasks; per-category tables (radar-relevant vs not); failures shown, never hidden; one-page method + configs in `/docs/methodology.md` written BEFORE polish, not after. Radical honesty is itself the feature: the ledger includes our useless radar fires and our failed tasks.
**Edge-case demo:** one "issue" task showing the radar firing and buying nothing — handled honestly on stage.

---

## 8. Phases (hour-budgeted; 3 people: P1 core / P2 gateway+suite / P3 tools+radar+eval)

**Phase 0 — spike + keys (≤3h, all together)**
- [ ] Register free tiers: Google AI Studio, Groq, **Tavily** (do this NOW).
- [ ] `npx -y @maximhq/bifrost` up on :8080; provider wired in web UI; 1 smoke chat capturing usage fields + `x-bifrost-cache-hit` headers.
- [ ] Semantic cache plugin ON, DIRECT mode (dimension: 1).
- [ ] Tavily API smoke: tiny query → snippet extraction.
- [ ] Task repos cloned & pinned; pick model (strongest free tool-caller of the three); lock stack choice.
- **Exit:** one call through Bifrost shows tokens; one Tavily call returns fresh doc info.

**Phase 1 — thin agent core (P1 ~8h; P2 parallel: suite builder; P3 parallel: verify CLI)**
- [ ] Agent loop with primitives: list_files, grep_excerpts, edit, run_tests, shell + ledger stub.
- [ ] Policy system prompt + hard budgets: no-re-read rule (crude version OK), plan-then-act, retry cap 3, stop-on-green.
- [ ] `--profile baseline` strawman mode (same loop, policy off, full-file reads).
- [ ] Usage ledger per call → `runs/<task>/ledger.json`.
- **Exit:** MISER solves 1 easy task end-to-end with real ledger numbers; strawman counter-profile runs.

**Phase 2 — receipts + baselines + graph (parallel ~10h)**
- P2: Bifrost receipt feed (tokens + cache status); OSS baseline agent installed headless.
- P1: Python tree-sitter graph (defs/imports; call-refs best-effort by name) + `blast_radius` + impacted-test selection.
- P3: `verify_claim` engine + `miser verify` CLI wrapper + freshness table (rich).
- **Exit:** `blast_radius` returns a real neighborhood; `miser verify` audits a sample stale answer.

**Phase 3 — tools complete (parallel ~8–10h)**
- [ ] `recall` (deltas), `zoom` (L0/L1/L2), `mutation_probe`, `supply_chain`, `receipt` comparator.
- [ ] Radar triggers integrated in loop (guess-not-in-repo → fire), cap 3/task, logged.
- **Exit:** every Tier-1 tool individually demoable in ≤30s each.

**Phase 4 — eval + demo polish (~8h + buffer)**
- [ ] Full suite run × all profiles; per-category tables; ablation column.
- [ ] Receipt ASCII tables (rich); simple terminal graph-walk visualization.
- [ ] README + `/docs/methodology.md` + rubric map slides.
- [ ] **Rehearse demo ×3 minimum**; mocker-plugin dry-run; backup video recorded; backup task ready.
- **Exit:** demo under 5 min, zero freezing steps.

---

## 9. Demo script (5:00, terminal, rehearsed)

| t | Beat |
| --- | --- |
| 0:00 | Hook: "Agents waste most tokens just reading." |
| 0:30 | OSS baseline on task: file-dump wall, thrash, **hallucinated deprecated API** → red test; show its receipt. |
| 1:45 | MISER same task: map → `zoom` L0→L1→L2 (meter ticking) → `recall` delta → edit → `blast_radius` → 3/47 tests → green. |
| 3:00 | Radar moment: policy pauses, `verify_claim` fires ONCE, ledger row shows source + date; `supply_chain` flags the stale/CVE dep. |
| 3:45 | `mutation_probe` proof: "we mutated the fix; tests died — the patch is load-bearing." |
| 4:15 | Scoreboard + both receipts side-by-side + rubric-map slide. |
| 4:45 | Compress: "Bifrost is the pump; MISER is the discipline." |

Failsafe: 2nd curated task ready; if live show dies, backup video plays; never improvise.

---

## 10. Risks (each has an owner)

| Risk | Mitigation | Owner |
| --- | --- | --- |
| Free model derps tool calls live | Rehearse ×3; mocker dry-run; model swap = 1 config line; backup task | P1 |
| Scope overflow (esp. graph) | Python-first hard rule; if graph slips: zoom+recall+receipt become flagship, graph = roadmap slide | P1 |
| "Rigged suite" accusation | ≤3 labelled radar-relevant tasks; per-category results; method published pre-demo | P3 |
| "Strawman" accusation | OSS agent headline baseline; ablations; configs public | P2 |
| Radar cost optics | Every fire logged incl. useless; radar spend in receipts | P3 |
| "You just enabled their cache" | Bifrost = referee/infrastructure; our claims = harness policy + tools; cache headers shown as metering evidence | P2 |
| Two-rubric masquerade | Rubric-compliance slide pair; `miser verify` standalone artifact | P1 |
| Keys never arrive | Free tiers registered Phase 0; mocker for rehearsal | P2 |
| Demo timeout | Stopwatch protocol; kill switches | All |

---

## 11. Environment setup (Phase 0, then freeze)

```bash
python -m venv .venv && source .venv/bin/activate
pip install typer rich tavily-python tree-sitter tree-sitter-language-pack openai
npx -y @maximhq/bifrost   # UI at http://localhost:8080 → wire free provider keys; enable semantic_cache DIRECT (dimension: 1)
export BIFROST_URL=http://localhost:8080/openai
export TAVILY_API_KEY=...
```
All calls: `base_url = http://localhost:8080/openai`, one model string, temperature 0 for evals. Receipt reads `usage` from responses + `x-bifrost-cache-*` headers.

---

## 12. Win-thesis freeze (for the stage and for us when tired)

In a field of hundreds of one-shot tricks (cache demos, prompt compression, generic RAG checkers), we win the room by showing a **mechanism, not a claim**: a fuel meter burning live, a ledger that admits its own misses, a patch that survives mutation, a real OSS agent wearing our tools (portability), and both rubrics explicitly ticked by separate artifacts. Execution quality — rehearsal and unflinching honest numbers — is the moat. If any of that is compromised, we did not build MISER; we built a shorter Rube Goldberg machine.
