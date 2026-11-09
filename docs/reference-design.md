# Reference designs

Reviewed upstream source on 2026-11-08. Branch links move; this is a focused
review of context management and editing, not a whole-repository audit.
MISER implements its own small mechanisms; no upstream source was copied.

| Source | Observation | MISER implementation |
| --- | --- | --- |
| [Aider repomap.py](https://github.com/Aider-AI/aider/blob/main/aider/repomap.py) | Symbol extraction, reference ranking, caching, and a map token budget | On-demand task-ranked paths and Python AST names with a strict character budget. Ranking uses path/name matching; graph ranking and persistent caches remain pending. |
| [Aider editblock_coder.py](https://github.com/Aider-AI/aider/blob/main/aider/coders/editblock_coder.py) | Reports failed search blocks and actual matching context to help retry | Exact-match errors report occurrence count and a focused-read recovery action. MISER retains strict file/version matching. |
| [OpenCode compaction.ts](https://github.com/anomalyco/opencode/blob/dev/packages/core/src/session/compaction.ts) | Structured checkpoint plus recent exchanges; compaction usage is accounted for | Up to eight factual tool breadcrumbs beside bounded complete tool turns. Compaction stores a structured digest per tool result (summary keys such as path, counts, exit status) instead of a raw truncation, keeps a bounded `decisions` deque, and re-injects those decisions only when a real compaction runs. The threshold drops from 75% to 55% of budget when one tool result is unusually large. Still no separate summarization model call. Expired reads can be explicitly refreshed. |
| [Aider io.py](https://github.com/Aider-AI/aider/blob/main/aider/io.py) | Prompt session, command completion, plain-terminal fallback, separated tool/assistant output | Raw-mode composer with persistent history and slash completion in the TUI; readline session and plain transcript remain as the fallback. User, assistant, tool, and error output stay distinct. |
| [Aider mdstream.py](https://github.com/Aider-AI/aider/blob/main/aider/mdstream.py) | Incremental Markdown rendering while tokens arrive | `miser/ui/render.MarkdownStream` formats completed lines and wraps long paragraphs as they stream; no Rich dependency. |
| [OpenCode patch-diff.tsx](https://github.com/anomalyco/opencode/blob/dev/packages/tui/src/component/patch-diff.tsx) | Per-hunk diff rendering with gutters and line numbers | `render.render_diff` groups by file with `+n −n` headers, hunk context, line-number gutters, and explicit truncation. |
| [OpenCode one-cell-spinner.tsx](https://github.com/anomalyco/opencode/blob/dev/packages/tui/src/component/one-cell-spinner.tsx) | Tiny animated indicator that does not dominate the layout | `miser/ui/spinner.WorkingIndicator` animates one line with real elapsed time and is a no-op without a TTY. |
| [OpenCode usage.tsx](https://github.com/anomalyco/opencode/blob/dev/packages/tui/src/component/usage.tsx) | Separates limits, usage, and model metadata on demand | `/status` and `/usage` separate tasks, requests, tools, provider tokens, local estimates, and unknown usage. |
| [OpenCode routes/home.tsx](https://github.com/anomalyco/opencode/blob/dev/packages/tui/src/routes/home.tsx) | Centered flex column: logo, max-width composer, footer slot, generous spacing | `miser/tui/screen.py` welcome: centered block logo, 76-column composer card with accent bar, model/budget metadata, cwd and shortcut row. MISER keeps its own branding. |
| [OpenCode prompt/index.tsx](https://github.com/anomalyco/opencode/blob/dev/packages/tui/src/component/prompt/index.tsx) | Placeholder examples, model metadata inside the composer, agent/command hints | TUI composer with placeholder, cursor, wrapped editing, persistent history, slash completion, and model/budget line. Ctrl+J/Alt+Enter adds a line; Enter submits. |
| [OpenCode session view](https://github.com/anomalyco/opencode/blob/dev/packages/tui/src/routes/session.tsx) | Scrollable messages with a pinned composer and compact status | Fixed-height transcript viewport, PgUp/PgDn scrolling with `↑ n lines` indicator, composer anchored above a one-line usage/status footer. |
| [OpenCode app.tsx](https://github.com/anomalyco/opencode/blob/dev/packages/tui/src/app.tsx) | Command registry for models, usage, sessions, and diff review | Slash commands, usage, diff review, and approvals are preserved inside the full-screen TUI. |

## Limits to measure

Breadcrumbs and maps add input tokens; they may improve navigation or may cost more
than they save on small tasks. The map is optional and requested by the model.
No improvement is claimed until a same-model comparison on pinned tasks is run.
Python symbols use AST; other languages currently receive paths and text tools.
