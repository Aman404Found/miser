# Terminal interface

MISER has two presentations over the same engine:

1. **Full-screen TUI** (default in an interactive terminal when Rich is available).
2. **Line-oriented fallback** for `--no-tui`, `--exec`, pipes, `NO_COLOR`, `MISER_PLAIN`,
   or an environment without Rich.

Both use the same agent loop, tools, workspace guards, approvals, receipts, and usage
accounting. Only presentation and input handling differ.

## Full-screen states

The application owns the alternate screen, hides the terminal cursor, enables bracketed
paste, and repaints a fixed-height frame in place. It never appends a new status line per
update.

### Welcome

With no conversation, MISER shows a deliberately composed, centered welcome screen:

```text
                                  ██  ██  ██████  ██████  ██████  █████
                                  ███ ██    ██    ██      ██      ██  ██
                                  ██ ███    ██    ██████  █████   █████
                                  ██  ██    ██        ██  ██      ██ ██
                                  ██  ██  ██████  ██████  ██████  ██  ██

                              focused coding agent  ·  type a task or /help

                   ▌  Ask anything… "Fix a failing test in pricing.py"
                   ▌
                   ▌ chat  ·  provider/model  ·  24k budget

                   ~/project          tab complete · ctrl+j newline · ctrl+d exit
```

- The block logo and composer are centered horizontally; the whole block is centered
  vertically when space allows, with a compact top-aligned fallback on short terminals.
- The composer has its own background, a single blue accent bar, a prompt placeholder,
  and a metadata row for agent mode, model, and budget.
- The working directory and shortcuts sit directly below the same card width.
- Typing `/` shows command suggestions inside the welcome composition.
- On terminals narrower than 48 columns the logo becomes a `M I S E R` wordmark and the
  hints shorten; no line is allowed to wrap or overflow.

### Active conversation

After the first submission the layout changes to a session view:

```text
  MISER  provider/model                                            680 tok · 1 task
──────────────────────────────────────────────────────────────────────────────────

  ▌ fix the percentage discount calculation.

    · baseline acceptance tests: failing (exit 1)
  ⏺ miser · provider/model
  Let me inspect the discount calculation.
    ✔ read · 0.0s
  The formula multiplies instead of subtracting the discount.
    ✔ edit · 0.0s
    ✔ acceptance tests passed

  ✔ tests passed  ·  0.8s
    680 provider tokens (600 in / 80 out) · 2 model requests · 4 tool calls

  pricing.py  +1 −1
    @@ -2,4 +2,4 @@
      5 -     return price * discount_percent / 100
      5 +     return price * (1 - discount_percent / 100)
    runs/session-…/patch.diff · /diff · /receipt

  ▌  Ask anything…
  tab complete · PgUp history · ctrl+d exit                ready · 680 tok · tests passed
```

- A compact header carries identity, model, scroll position, provider tokens, and task count.
- The transcript starts at the top for a short conversation. Once it exceeds the viewport
  it is bottom-anchored above the composer; `PgUp`/`PgDn` scroll and the header shows
  `↑ n lines`.
- User messages use a `▌` accent; assistant replies are labelled `⏺ miser · model`; tool
  activity, baseline vs post-edit tests, compaction, fallbacks, and errors keep their own
  distinct lines and colours.
- The composer is always anchored above a one-line footer. It grows up to four wrapped rows
  and scrolls internally for longer prompts.
- While a task runs, the footer shows a real spinner, the current tool/thinking status, and
  elapsed time. There is no artificial progress or fake streaming.

## Composer and keys

| Input | Effect |
| --- | --- |
| printable characters / bracketed paste | insert at the cursor; pasted newlines are preserved |
| Enter | submit the prompt or slash command |
| Ctrl+J or Alt+Enter | insert a newline (multiline prompt) |
| ← / → / Home / End | move the cursor; kills movement respects wrapped hard lines |
| ↑ / ↓ | prompt history; moves between lines when the draft is multiline |
| Ctrl+P / Ctrl+N | previous / next history entry |
| Tab | complete and discover slash commands; ambiguous matches are listed |
| Ctrl+U | clear the current draft |
| PgUp / PgDn | scroll conversation history |
| Esc | return the transcript to the newest lines and dismiss suggestions |
| Ctrl+C | interrupt a running task; reject an approval; otherwise clear the draft |
| Ctrl+D | exit when no task is running |
| `/exit`, `/quit` | exit |
| `/clear` | clear the transcript and return to the welcome screen |

Prompt history is persisted in `.miser/history` and loaded at startup. Submission is
ignored while a task is running (the draft is retained; the status says to cancel first),
so two model tasks cannot overlap.

Slash commands keep their existing behavior: `/help`, `/status`, `/usage`, `/model`,
`/architect`, `/budget`, `/map`, `/diff`, `/test`, `/run`, `/receipt`, `/confirm`,
`/autocommit`, `/undo`, `/history`, `/clear`, `/exit`.

## Diffs and approvals

When `/confirm on` is active, the worker pauses and the TUI shows the proposed edit plus a
width-aware diff in the transcript. `y`/Enter approves, `n`/Esc rejects, `a` disables
approval for the rest of the session and approves, and `d` appends the full diff and keeps
waiting. Ctrl+C during approval rejects and requests cancellation. The same workspace
protections remain in force: protected test paths, exact matches, version checks, atomic
multi-file writes.

## Rendering lifecycle

- `miser/tui/screen.py` is pure layout: state + terminal dimensions → exactly *height* Rich
  lines of exactly *width* cells. Welcome centering, conversation regions, wrapping,
  cursor placement, and narrow layouts are unit-tested without a terminal.
- `miser/tui/io.py` enters the alternate screen, hides the cursor, enables bracketed paste,
  and draws one frame with cursor-home, line erases, and no trailing newline. Raw input
  mode disables canonical input, echo, `ISIG`, and `ICRNL` but keeps output processing, so
  Ctrl+C arrives as a byte and Enter remains distinguishable from Ctrl+J.
- `miser/tui/keys.py` decodes UTF-8, CSI arrows/home/end/paging/delete, shifted arrows,
  Alt+Enter, bracketed paste, and control keys. Incomplete sequences are buffered across
  reads.
- `miser/tui/app.py` owns the loop: redraw on change/spinner/size, drain all available keys
  before repainting, route `Terminal` output into the transcript, run `Terminal.task` on a
  worker thread, and hand approvals back to the UI thread. Terminal state is restored in
  `finally` on normal exit, Ctrl+D, `/exit`, cancellation, or an exception.
- `miser/terminal.py` remains the engine. Two small seams were added: an activity listener
  for status, and a cooperative `cancel_event` checked between model/tool steps. It also
  accepts a width override so output wraps to the transcript width instead of being clipped
  by its margins.
- Rich supplies styled text and ANSI conversion. Textual was evaluated but could not be
  installed in this environment (PEP 668, externally managed); a direct alternate-screen
  renderer keeps the lifecycle explicit and avoids a required dependency. Install the
  optional extra with `pip install 'miser-agent[tui]'`; without Rich, `chat` uses the line UI.

## Streaming and progress

Streaming, activity events, and billing are unchanged from the engine: SSE chunks are
assembled with usage, tool calls are rendered with real elapsed time, and interrupted
streams are never resent. The TUI displays a one-cell spinner with elapsed time and the
latest tool activity in the footer. Compaction, model fallback, architect planning, and
baseline/post-edit tests surface as their own statuses and transcript lines.

## Non-interactive use

```bash
python3 -m miser chat --no-tui
python3 -m miser chat --no-stream --exec "Fix the discount calculation"
python3 -m miser chat --no-tui --exec "hi"
```

`--exec` always uses the line transcript; `--no-tui` forces it for interactive use.
`NO_COLOR`, `MISER_PLAIN`, a non-TTY stream, or missing Rich also select it automatically.
Output stays plain for logs and CI.

## Verification and limits

- The full suite (`python3 -m unittest discover -s tests -q`) covers the pure welcome and
  conversation layouts, narrow/short terminals, scrolling, cursor placement, key decoding,
  editing/history/completion, slash handling, approval handshakes, cancellation, persistent
  history, usage labels, non-interactive selection, and the existing agent/workspace tests.
- End-to-end frames were captured through a real pseudo-terminal at **118×40** and
  **60×20** against the local OpenAI-compatible test double: welcome, working (spinner and
  tool activity), completed response with a diff, narrow conversation, and narrow welcome
  after `/clear`. The run exited with code 0; the alternate screen was entered and restored.
  Screenshots were rendered from the captured cells and inspected. This is protocol/UI
  verification, not a live-provider or latency benchmark.
- No live Bifrost gateway was running during this pass, so real-provider streaming and
  latency remain unverified.

Known limitations:

- No mouse selection, drag scrolling, or copy mode inside the alternate screen.
- A cancelled in-flight HTTP request is closed after the stream callback notices the
  cancellation; provider billing for that request may already be unknown (the receipt says so).
- The TUI requires a Unicode-capable terminal to show its icons; the line fallback is
  available when glyph support is a concern.
- Streamed Markdown is formatted per completed line; syntax highlighting inside code fences
  is not implemented.
- Wide/ambiguous character widths use `unicodedata.east_asian_width` and may differ from a
  particular terminal font.
- The conversation is keyboard-scrollable only; the transcript is not a terminal scrollback
  buffer once the alternate screen is active.
