"""Compatibility shim over :mod:`miser.ui`.

Older call sites import styling helpers from here; the implementation lives in
``miser/ui/theme.py`` and ``miser/ui/render.py`` so rendering has one home.
"""

from .ui import render, theme

bold = theme.bold
dim = theme.dim
italic = theme.italic
red = theme.red
green = theme.green
yellow = theme.yellow
blue = theme.blue
magenta = theme.magenta
cyan = theme.cyan
gray = theme.gray
clean = theme.clean
visible_len = theme.visible_len
is_color_enabled = theme.color_enabled


def badge(text, color_fn=green):
    return color_fn(f"[{text}]")


def format_card(title, items, width=68):
    return render.panel(title, items, width)


def format_diff(diff_text):
    return render.render_diff(diff_text, theme.term_width(), max_lines=None)


def human_tool_progress(name, args):
    """Concise, human-readable progress description for a tool invocation."""
    detail = render.tool_detail(name, args)
    label = render.TOOL_LABELS.get(name, name)
    if name == "repo_map":
        query = (args.get("query") or "").strip()
        return f"· Indexing symbols{f' for {query}' if query else ''}"
    if name == "list_files":
        return "· Listing workspace files"
    if name == "run_tests":
        return "· Running acceptance tests"
    if name == "edit_batch":
        return f"· Applying atomic changeset to {detail or 'files'}"
    return f"· {label.capitalize()} {detail}".rstrip()
