"""Bounded text access for any language; Python structure via the built-in AST."""

import ast
import difflib
import fnmatch
import hashlib
import os
import re
from pathlib import Path


EXCLUDED = {".git", ".agents", ".codex", ".aws", ".ssh", ".venv", "venv", "node_modules",
            "__pycache__", "dist", "build", "runs", ".next", ".pytest_cache", ".miser"}
SECRET_SUFFIXES = {".pem", ".key", ".p12", ".pfx"}


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


def _glob_match(name, pattern):
    """fnmatch plus the shell rule that '**/' may also match no directory."""
    pending = [pattern]
    seen = set()
    while pending:
        candidate = pending.pop()
        if candidate in seen:
            continue
        seen.add(candidate)
        if fnmatch.fnmatch(name, candidate):
            return True
        index = candidate.find("**/")
        while index != -1:
            pending.append(candidate[:index] + candidate[index + 3:])
            index = candidate.find("**/", index + 3)
    return False


def find_whitespace_normalized_match(current: str, old: str, new: str):
    """
    Find old in current using whitespace/indentation-tolerant matching (Aider-style).
    Returns (replacement, True) if a single, unambiguous match is found;
    otherwise (None, False).
    """
    current_lines = current.splitlines(keepends=True)
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    if not old_lines or not current_lines:
        return None, False

    num_old = len(old_lines)
    candidates = []

    # 1. Trailing whitespace differences (common when LLMs strip trailing whitespace)
    old_rstripped = [l.rstrip("\r\n \t") for l in old_lines]
    for i in range(len(current_lines) - num_old + 1):
        window = current_lines[i : i + num_old]
        if [l.rstrip("\r\n \t") for l in window] == old_rstripped:
            candidates.append((i, 0))

    # 2. Uniform leading indentation shift (e.g. LLM omitted outer indentation)
    if not candidates:
        old_stripped = [l.strip() for l in old_lines]
        for i in range(len(current_lines) - num_old + 1):
            window = current_lines[i : i + num_old]
            if [l.strip() for l in window] == old_stripped:
                shifts = []
                for w, o in zip(window, old_lines):
                    if w.strip():
                        w_indent = len(w) - len(w.lstrip(" "))
                        o_indent = len(o) - len(o.lstrip(" "))
                        shifts.append(w_indent - o_indent)
                if shifts and all(s == shifts[0] for s in shifts):
                    candidates.append((i, shifts[0]))

    if len(candidates) == 1:
        start_idx, indent_shift = candidates[0]
        adjusted_new = []
        for line in new_lines:
            if not line.strip():
                adjusted_new.append(line)
            elif indent_shift > 0:
                adjusted_new.append(" " * indent_shift + line)
            elif indent_shift < 0:
                dedent = -indent_shift
                leading = len(line) - len(line.lstrip(" "))
                adjusted_new.append(line[min(dedent, leading):])
            else:
                adjusted_new.append(line)

        new_block = "".join(adjusted_new)
        if not new_block.endswith("\n") and current_lines[start_idx + num_old - 1].endswith("\n"):
            new_block += "\n"

        replacement = "".join(current_lines[:start_idx]) + new_block + "".join(current_lines[start_idx + num_old:])
        return replacement, True

    return None, False


HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_unified_diff(patch_text):
    """
    Parse a standard git-style unified diff into [(path, [(old_start, old_block, new_block), ...])].
    Raises ValueError for malformed hunks, file creation/deletion, or hunk-count mismatches.
    """
    if not isinstance(patch_text, str) or not patch_text.strip():
        raise ValueError("Patch must be nonempty unified diff text")
    lines = patch_text.splitlines(keepends=True)
    files = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if not (line.startswith("--- ") and i + 1 < len(lines) and lines[i + 1].startswith("+++ ")):
            i += 1
            continue
        source = line[4:].strip()
        target = lines[i + 1][4:].strip()
        if source == "/dev/null" or target == "/dev/null":
            raise ValueError("Creating or deleting files is not supported; edit an existing file")
        if target.startswith("b/"):
            target = target[2:]
        i += 2
        hunks = []
        while i < len(lines):
            header = HUNK_HEADER.match(lines[i])
            if not header:
                if lines[i].startswith("--- ") or lines[i].startswith("diff --git"):
                    break
                i += 1
                continue
            old_start = int(header.group(1))
            old_count = int(header.group(2)) if header.group(2) is not None else 1
            new_count = int(header.group(4)) if header.group(4) is not None else 1
            i += 1
            hunk_body = []
            while i < len(lines) and not lines[i].startswith("@@") \
                    and not lines[i].startswith("--- ") and not lines[i].startswith("diff --git"):
                hunk_body.append(lines[i])
                i += 1
            old_lines, new_lines = [], []
            for raw in hunk_body:
                if raw.startswith("\\"):
                    # "\ No newline at end of file" applies to the preceding line.
                    for side in (old_lines, new_lines):
                        if side:
                            side[-1] = side[-1].rstrip("\r\n")
                    continue
                if raw in ("\n", "\r\n", ""):
                    old_lines.append(raw)
                    new_lines.append(raw)
                    continue
                tag, body = raw[:1], raw[1:]
                if tag == "-":
                    old_lines.append(body)
                elif tag == "+":
                    new_lines.append(body)
                elif tag == " ":
                    old_lines.append(body)
                    new_lines.append(body)
                else:
                    raise ValueError(f"Malformed hunk line {raw!r}; expected ' ', '+', '-' or '\\'")
            if len(old_lines) != old_count or len(new_lines) != new_count:
                raise ValueError(
                    f"Hunk header @@ -{header.group(1)},{header.group(2)} +{header.group(3)},{header.group(4)} @@ "
                    f"does not match its body (found {len(old_lines)} old / {len(new_lines)} new lines)")
            if not old_lines:
                raise ValueError("Hunk contains only additions; include surrounding context lines")
            hunks.append((old_start, "".join(old_lines), "".join(new_lines)))
        if hunks:
            files.append((target, hunks))
    if not files:
        raise ValueError("No unified diff file blocks found (expected --- a/... and +++ b/...)")
    return files


def diff_previews(patch_text):
    """Return {path: preview} of the raw hunks in a unified diff, for approval prompts."""
    lines = patch_text.splitlines(keepends=True)
    previews, current = {}, None
    for line in lines:
        if line.startswith("+++ "):
            current = line[4:].strip()
            if current.startswith("b/"):
                current = current[2:]
            previews.setdefault(current, [])
        elif current is not None and not line.startswith("--- ") and (
                line.startswith("@@") or line[:1] in (" ", "+", "-") or line.startswith("\\")):
            previews[current].append(line)
    return {path: "".join(chunks) for path, chunks in previews.items()}


def numbered_region(lines, line_no, before=4, after=8, width=3000):
    """Numbered snippet around `line_no` so an error can show the real text."""
    if not lines or not line_no:
        return ""
    start = max(1, line_no - before)
    end = min(len(lines), line_no + after)
    snippet = "\n".join(f"{i}: {lines[i - 1].rstrip(chr(13) + chr(10))[:400]}" for i in range(start, end + 1))
    return snippet[:width]


def find_closest_match_line(current: str, old: str):
    """Find line number in current where old lines or its primary line appears."""
    old_lines = [l.strip() for l in old.splitlines() if l.strip()]
    if not old_lines:
        return None
    target = old_lines[0]
    current_lines = current.splitlines()
    for i, line in enumerate(current_lines, 1):
        if target in line or (line.strip() and line.strip() in target):
            return i
    matches = difflib.get_close_matches(target, [l.strip() for l in current_lines if l.strip()], n=1, cutoff=0.4)
    if matches:
        for i, line in enumerate(current_lines, 1):
            if line.strip() == matches[0]:
                return i
    # Check by common words (e.g. "return" or function names)
    target_words = set(re.findall(r"[a-zA-Z_]\w*", target))
    best_score, best_line = 0, None
    for i, line in enumerate(current_lines, 1):
        line_words = set(re.findall(r"[a-zA-Z_]\w*", line))
        overlap = len(target_words & line_words)
        if overlap > best_score:
            best_score = overlap
            best_line = i
    if best_score >= 1:
        return best_line
    return None


class Workspace:
    def __init__(self, root, policy=True):
        self.root = Path(root).resolve()
        if not self.root.is_dir():
            raise ValueError("Repository path must be a directory")
        self.policy = policy
        self.snapshots = {}
        self.reads = set()
        self.modified = set()
        self.originals = {}
        self.last_written = {}
        self.symbol_cache = {}

    def path(self, name):
        relative = Path(name)
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise ValueError("Use a relative path inside the repository")
        if any(p in EXCLUDED or p.startswith(".env") for p in relative.parts):
            raise ValueError("Excluded or sensitive path")
        if relative.suffix.lower() in SECRET_SUFFIXES:
            raise ValueError("Sensitive file type")
        candidate = self.root / relative
        for parent in [candidate, *candidate.parents]:
            if parent == self.root:
                break
            if parent.is_symlink():
                raise ValueError("Symlinks are not accessible")
        if not candidate.resolve().is_relative_to(self.root):
            raise ValueError("Path escapes repository")
        return candidate

    def text(self, name):
        path = self.path(name)
        if path.stat().st_size > 250_000:
            raise ValueError("File exceeds 250 KB; narrow the task outside MISER first")
        value = path.read_text(encoding="utf-8")
        if "\x00" in value:
            raise ValueError("Binary file")
        return value

    def files(self):
        names = []
        for parent, dirs, files in os.walk(self.root, followlinks=False):
            dirs[:] = sorted(d for d in dirs if d not in EXCLUDED and not d.startswith(".env")
                              and not (Path(parent) / d).is_symlink())
            for file in sorted(files):
                name = (Path(parent) / file).relative_to(self.root).as_posix()
                try:
                    self.path(name)
                except ValueError:
                    continue
                names.append(name)
                if len(names) >= 5000:
                    return names
        return names

    def list_files(self):
        names = self.files()
        return {"files": names[:300], "truncated": len(names) > 300,
                "note": "Generated directories and common credential files excluded."}

    def scope(self, cwd=""):
        """Normalize an optional subdirectory argument to a repo-relative prefix."""
        if cwd is None:
            return ""
        if not isinstance(cwd, str):
            raise ValueError("cwd must be a directory path relative to the repository")
        cleaned = cwd.strip().replace("\\", "/").strip("/")
        while cleaned.startswith("./"):
            cleaned = cleaned[2:]
        if cleaned in ("", "."):
            return ""
        candidate = self.path(cleaned)
        if not candidate.is_dir():
            raise ValueError(f"'{cleaned}' is not a directory in the repository")
        return cleaned

    def find_files(self, pattern, limit=100, cwd=""):
        """Glob file names, optionally scoped to a subdirectory."""
        if not isinstance(pattern, str) or not pattern.strip():
            raise ValueError("Pattern must be a nonempty glob such as '**/*.py' or 'miser/*.py'")
        if len(pattern) > 200:
            raise ValueError("Pattern must be at most 200 characters")
        if not isinstance(limit, int) or not 1 <= limit <= 500:
            raise ValueError("Limit must be 1–500")
        prefix = self.scope(cwd)
        cleaned = pattern.strip().replace("\\", "/")
        if cleaned.startswith("./"):
            cleaned = cleaned[2:]
        full = f"{prefix}/{cleaned}" if prefix else cleaned
        if "**" in full:
            names = [name for name in self.files() if _glob_match(name, full)]
        else:
            names = []
            for candidate in self.root.glob(full):
                if not candidate.is_file():
                    continue
                name = candidate.relative_to(self.root).as_posix()
                try:
                    self.path(name)
                except ValueError:
                    continue
                names.append(name)
            names.sort()
        unique = sorted(set(names))
        result = {"pattern": cleaned, "files": unique[:limit], "truncated": len(unique) > limit}
        if prefix:
            result["cwd"] = prefix
        return result

    def search(self, query, limit=20, context=0, cwd=""):
        if not query or len(query) > 300:
            raise ValueError("Query must contain 1–300 characters (literal search)")
        if not isinstance(context, int) or not 0 <= context <= 5:
            raise ValueError("Context must be 0–5 lines")
        prefix = self.scope(cwd)
        cap = max(1, min(limit, 50))
        matches = []
        for name in self.files():
            if prefix and not name.startswith(prefix + "/"):
                continue
            try:
                lines = self.text(name).splitlines()
            except (OSError, UnicodeError, ValueError):
                continue
            for number, line in enumerate(lines, 1):
                if query in line:
                    match = {"path": name, "line": number, "text": line[:400]}
                    if context:
                        low = max(1, number - context)
                        high = min(len(lines), number + context)
                        match["context"] = [{"line": i, "text": lines[i - 1][:400]}
                                            for i in range(low, high + 1)]
                    matches.append(match)
                    if len(matches) >= cap:
                        result = {"matches": matches, "truncated": True}
                        if prefix:
                            result["cwd"] = prefix
                        return result
        result = {"matches": matches, "truncated": False}
        if prefix:
            result["cwd"] = prefix
        return result

    @staticmethod
    def extract_js_symbols(text, terms=None):
        terms = terms or set()
        patterns = [
            re.compile(r'^\s*(?:export\s+)?(?:async\s+)?function\s+([a-zA-Z_$][a-zA-Z0-9_$]*)'),
            re.compile(r'^\s*(?:export\s+)?class\s+([a-zA-Z_$][a-zA-Z0-9_$]*)'),
            re.compile(r'^\s*(?:export\s+)?(?:const|let|var)\s+([a-zA-Z_$][a-zA-Z0-9_$]*)\s*=\s*(?:async\s*)?(?:\([^)]*\)|[a-zA-Z_$][a-zA-Z0-9_$]*)\s*=>'),
        ]
        symbols = []
        for lineno, line in enumerate(text.splitlines(), 1):
            for pat in patterns:
                m = pat.match(line)
                if m:
                    symbols.append({"name": m.group(1), "line": lineno})
                    break
        symbols.sort(key=lambda s: (-sum(t in s["name"].lower() for t in terms), s["line"]))
        return symbols

    def symbols(self, name, text=None):
        """Cached definition list for a file, keyed by (path, mtime_ns, size)."""
        try:
            stat = self.path(name).stat()
        except OSError:
            return []
        cache_key = (name, stat.st_mtime_ns, stat.st_size)
        if cache_key in self.symbol_cache:
            return self.symbol_cache[cache_key]
        if text is None:
            try:
                text = self.text(name)
            except (ValueError, OSError, UnicodeError):
                self.symbol_cache[cache_key] = []
                return []
        symbols = []
        if name.endswith(".py"):
            try:
                tree = ast.parse(text)
            except (SyntaxError, ValueError):
                self.symbol_cache[cache_key] = []
                return []
            symbols = [{"name": node.name, "line": node.lineno,
                        "kind": "class" if isinstance(node, ast.ClassDef) else "def"}
                       for node in ast.walk(tree)
                       if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))]
        elif name.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
            symbols = [{"name": item["name"], "line": item["line"], "kind": "def"}
                       for item in self.extract_js_symbols(text)]
        symbols.sort(key=lambda item: item["line"])
        self.symbol_cache[cache_key] = symbols
        return symbols

    def repo_map(self, query="", max_chars=4000):
        if not isinstance(max_chars, int) or not 500 <= max_chars <= 8000:
            raise ValueError("Map budget must be 500–8000 characters")
        if len(query) > 1000:
            raise ValueError("Map query must be at most 1000 characters")
        from .repomap import RepoMap
        return RepoMap(self).build(query, max_chars)

    def zoom(self, path, level=0, start=1, end=None, symbol=None, refresh=False):
        if level not in (0, 1, 2):
            raise ValueError("Level must be 0 (outline), 1 (symbol), or 2 (line window)")
        text = self.text(path)
        lines = text.splitlines()
        version = digest(text)
        key = (path, level, start, end, symbol, version)
        if self.policy and key in self.reads and not refresh:
            return {"unchanged": True, "version": version,
                    "hint": "Already read. Use recall for changes; set refresh=true if the original read expired from history."}
        if level == 0:
            if path.endswith(".py"):
                tree = ast.parse(text)
                outline = []
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                        outline.append({"name": node.name, "start": node.lineno, "end": node.end_lineno,
                                        "signature": lines[node.lineno - 1].strip()[:250]})
                content = {"analysis": "python-ast", "symbols": sorted(outline, key=lambda x: x["start"])[:100]}
            elif path.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
                js_syms = self.extract_js_symbols(text)
                outline = [{"name": s["name"], "start": s["line"], "end": s["line"],
                            "signature": lines[s["line"] - 1].strip()[:250]} for s in js_syms]
                content = {"analysis": "javascript-structure", "symbols": outline[:100]}
            else:
                # No fake symbol graph for languages without a parser yet.
                content = {"analysis": "text-preview", "preview": self.numbered(lines, 1, min(20, len(lines))),
                           "note": "Use literal search and line windows. No structural parser for this language yet."}
        else:
            if level == 1:
                if path.endswith(".py"):
                    if not symbol:
                        raise ValueError("Symbol zoom currently requires a symbol name")
                    nodes = [n for n in ast.walk(ast.parse(text)) if isinstance(
                        n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) and n.name == symbol]
                    if len(nodes) != 1:
                        raise ValueError("Symbol missing or ambiguous; use a line window")
                    start, end = nodes[0].lineno, nodes[0].end_lineno
                elif path.endswith((".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")):
                    if not symbol:
                        raise ValueError("Symbol zoom requires a symbol name")
                    js_matches = [s for s in self.extract_js_symbols(text) if s["name"] == symbol]
                    if len(js_matches) != 1:
                        raise ValueError("Symbol missing or ambiguous; use a line window")
                    start = js_matches[0]["line"]
                    end = min(start + 40, len(lines))
                else:
                    raise ValueError("Symbol zoom requires Python or JavaScript/TypeScript path; use level 2 otherwise")
            end = min(end if end is not None else start + 79, start + 119, len(lines))
            if start < 1 or start > max(1, len(lines)) or end < start:
                raise ValueError("Invalid line range")
            content = {"start": start, "end": end, "text": self.numbered(lines, start, end)}
        # A second model round trip to expand a tiny outline costs more than
        # including the small body once. Bound bytes and lines across languages.
        if level == 0 and len(lines) <= 40 and len(text.encode("utf-8")) <= 2000 and all(len(line) <= 1000 for line in lines):
            content.update(text=self.numbered(lines, 1, len(lines)), start=1,
                           end=len(lines), complete=True)
        self.reads.add(key)
        self.snapshots[path] = text
        return {"path": path, "version": version, **content}

    @staticmethod
    def numbered(lines, start, end):
        return "\n".join(f"{i}: {lines[i-1][:1000]}" for i in range(start, end + 1))

    READ_MANY_LIMIT = 8

    def read_many(self, reads, max_chars=24000):
        """Read several bounded line windows in one call, sharing one character budget."""
        if not isinstance(reads, list) or not reads:
            raise ValueError("read_many requires a non-empty list of reads")
        if len(reads) > self.READ_MANY_LIMIT:
            raise ValueError(f"read_many accepts at most {self.READ_MANY_LIMIT} files per call")
        if not isinstance(max_chars, int) or not 2000 <= max_chars <= 60000:
            raise ValueError("max_chars must be 2000–60000")
        results = []
        remaining = max_chars
        for entry in reads:
            if not isinstance(entry, dict) or not isinstance(entry.get("path"), str) or not entry["path"]:
                raise ValueError("Each read needs a 'path' string")
            name = entry["path"]
            try:
                text = self.text(name)
            except (OSError, UnicodeError, ValueError) as error:
                results.append({"path": name, "error": str(error)})
                continue
            lines = text.splitlines()
            version = digest(text)
            start = entry.get("start")
            start = 1 if start is None else start
            if not isinstance(start, int) or start < 1:
                raise ValueError(f"Invalid start line for '{name}'")
            if not lines:
                results.append({"path": name, "version": version, "start": 1, "end": 0,
                                "total_lines": 0, "text": "", "truncated": False})
                self.snapshots[name] = text
                continue
            start = min(start, len(lines))
            end = entry.get("end")
            end = start + 119 if end is None else end
            if not isinstance(end, int) or end < start:
                raise ValueError(f"Invalid line range for '{name}'")
            end = min(end, start + 119, len(lines))
            body = self.numbered(lines, start, end)
            cost = len(body) + 1
            truncated = False
            if remaining <= 1:
                results.append({"path": name, "error":
                                "Read budget exhausted for this call; read this file in a separate call."})
                continue
            if cost > remaining:
                body = body[:remaining]
                cost = len(body)
                truncated = True
            remaining = max(0, remaining - cost)
            self.snapshots[name] = text
            self.reads.add((name, 2, start, end, None, version))
            results.append({"path": name, "version": version, "start": start, "end": end,
                            "total_lines": len(lines), "text": body, "truncated": truncated})
        return {"reads": results, "budget": max_chars, "remaining": remaining}

    def write_file(self, path, content):
        """Create a new file with complete text; existing files must use edit."""
        if not isinstance(content, str):
            raise ValueError("Content must be text")
        if not content:
            raise ValueError("Content must be nonempty")
        if len(content.encode("utf-8")) > 200_000:
            raise ValueError("File exceeds 200 KB; create a smaller file and extend it with edit")
        target = self.path(path)
        if target.exists() or target.is_symlink():
            raise ValueError(f"'{path}' already exists. Use zoom then edit (or apply_patch) instead")
        if not target.parent.is_dir():
            raise ValueError(f"Directory for '{path}' does not exist; MISER will not create directories")
        try:
            target.write_text(content, encoding="utf-8")
        except OSError as error:
            raise RuntimeError(f"Could not create '{path}': {error}") from error
        self.originals[path] = None  # sentinel: the file did not exist before this session
        self.last_written[path] = content
        self.snapshots[path] = content
        self.modified.add(path)
        self.symbol_cache.clear()
        return {"path": path, "version": digest(content), "created": True}

    def recall(self, path):
        if path not in self.snapshots:
            raise ValueError("Read this file with zoom first")
        previous, current = self.snapshots[path], self.text(path)
        delta = "\n".join(difflib.unified_diff(previous.splitlines(), current.splitlines(),
                                              fromfile=path + " (last read)", tofile=path, n=2))
        self.snapshots[path] = current
        return {"path": path, "version": digest(current), "unchanged": current == previous,
                "delta": delta[:10000], "truncated": len(delta) > 10000,
                "note": "Delta compares file snapshots; previous snippets may have left the bounded model history."}

    def edit(self, path, old, new, expected_version):
        if path not in self.snapshots:
            raise ValueError("Read with zoom before editing")
        current = self.text(path)
        if digest(current) != expected_version:
            raise ValueError("File changed since read. Recall or zoom before editing")
        if not old:
            raise ValueError("Old text must be nonempty and match exactly once (matches=0). Zoom the affected lines with refresh=true and copy exact text.")
        if len(new) > 20000:
            raise ValueError("Patch too large")

        if current.count(old) == 1:
            replacement = current.replace(old, new, 1)
        elif current.count(old) > 1:
            matches = current.count(old)
            raise ValueError(f"Old text must be nonempty and match exactly once (matches={matches}). Include more surrounding lines to identify one occurrence.")
        else:
            # 0 matches: attempt whitespace/indentation-normalized matching (Aider-style)
            replacement, matched = find_whitespace_normalized_match(current, old, new)
            if not matched:
                line_no = find_closest_match_line(current, old)
                if line_no is not None:
                    region = numbered_region(current.splitlines(), line_no)
                    hint = (f"Old text was not found. Similar code exists around line {line_no}. "
                            f"Use zoom('{path}', level=2, start={max(1, line_no - 4)}, end={line_no + 8}, refresh=True) "
                            f"to copy exact lines. Nearby numbered text:\n{region}")
                else:
                    hint = "Zoom the affected lines with refresh=true and copy exact text."
                raise ValueError(f"Old text must be nonempty and match exactly once (matches=0). {hint}")

        if replacement == current:
            raise ValueError("Patch makes no change")
        self.originals.setdefault(path, current)
        self.path(path).write_text(replacement, encoding="utf-8")
        self.last_written[path] = replacement
        self.modified.add(path)
        return {"path": path, "version": digest(replacement), "edited": True}

    def edit_batch(self, edits: list[dict]):
        """
        Atomically apply multiple edits across one or more files.
        Each edit dict must contain: 'path', 'old', 'new', 'expected_version'.
        If any edit fails validation or cannot be matched, NO files on disk are modified.
        """
        if not edits:
            raise ValueError("Edit batch must contain at least one edit")
        if len(edits) > 10:
            raise ValueError("Edit batch exceeds 10 operations limit")

        staged_files = {}

        # 1. First pass: validate all snapshots, versions, and match replacements in memory
        for idx, item in enumerate(edits):
            path = item.get("path")
            old = item.get("old")
            new = item.get("new")
            expected_ver = item.get("expected_version")
            if not path or old is None or new is None or not expected_ver:
                raise ValueError(f"Edit #{idx + 1} is missing required fields (path, old, new, expected_version)")

            if path not in self.snapshots:
                raise ValueError(f"Read '{path}' with zoom before editing (edit #{idx + 1})")

            if path in staged_files:
                current_text = staged_files[path]
            else:
                current_text = self.text(path)
                if digest(current_text) != expected_ver:
                    raise ValueError(f"File '{path}' changed since read (edit #{idx + 1}). Recall or zoom before editing")

            if not old:
                raise ValueError(f"Old text in edit #{idx + 1} for '{path}' must be nonempty")
            if len(new) > 20000:
                raise ValueError(f"Patch in edit #{idx + 1} too large")

            if current_text.count(old) == 1:
                replacement = current_text.replace(old, new, 1)
            elif current_text.count(old) > 1:
                matches = current_text.count(old)
                raise ValueError(f"Old text in edit #{idx + 1} matches {matches} times in '{path}'. Include more surrounding lines to identify one occurrence.")
            else:
                replacement, matched = find_whitespace_normalized_match(current_text, old, new)
                if not matched:
                    line_no = find_closest_match_line(current_text, old)
                    if line_no:
                        hint = (f"Similar code exists around line {line_no}. Nearby numbered text:\n"
                                f"{numbered_region(current_text.splitlines(), line_no)}")
                    else:
                        hint = "Zoom affected lines with refresh=true."
                    raise ValueError(f"Old text in edit #{idx + 1} not found in '{path}'. {hint}")

            if replacement == current_text:
                raise ValueError(f"Edit #{idx + 1} makes no change to '{path}'")

            staged_files[path] = replacement

        # 2. Second pass: write every staged file, restoring all of them on failure.
        return self.write_batch(staged_files)

    def write_batch(self, staged):
        """
        Write fully-built new file contents for one or more files as one transaction.
        `staged` maps relative path -> complete new file text. Every file must have been
        read with zoom. If any write fails, files written by this call are restored to
        their contents from before the call.
        """
        if not staged:
            raise ValueError("Write batch must contain at least one file")
        originals = {}
        for path, new_text in staged.items():
            if path not in self.snapshots:
                raise ValueError(f"Read '{path}' with zoom before editing")
            current = self.text(path)
            if current == new_text:
                raise ValueError(f"Patch makes no change to '{path}'")
            originals[path] = current

        previously_modified = set(self.modified)
        previous_written = dict(self.last_written)
        written = []
        try:
            for path, new_text in staged.items():
                self.originals.setdefault(path, originals[path])
                self.path(path).write_text(new_text, encoding="utf-8")
                self.last_written[path] = new_text
                written.append(path)
                self.modified.add(path)
        except OSError as error:
            for path in written:
                try:
                    self.path(path).write_text(originals[path], encoding="utf-8")
                    if path in previous_written:
                        self.last_written[path] = previous_written[path]
                    else:
                        self.last_written.pop(path, None)
                    if path not in previously_modified:
                        self.modified.discard(path)
                except OSError:
                    continue
            raise RuntimeError(f"Atomic batch write failed, rolled back changes: {error}") from error

        return {"edited": True, "files": sorted(staged),
                "versions": {path: digest(text) for path, text in staged.items()}}

    @staticmethod
    def _apply_hunk(lines, old_start, old_block, new_block, path):
        """Apply one verified hunk to `lines`, preferring the header's line position."""
        old_lines = old_block.splitlines(keepends=True)
        new_lines = new_block.splitlines(keepends=True)
        size = len(old_lines)
        matches = [i for i in range(len(lines) - size + 1) if lines[i:i + size] == old_lines]
        if not matches:
            line_no = find_closest_match_line("".join(lines), old_block)
            hint = (f" Similar code exists around line {line_no}. Nearby numbered text:\n"
                    f"{numbered_region(lines, line_no)}") if line_no else ""
            raise ValueError(f"Hunk at line {old_start} does not match '{path}'.{hint} "
                             "Zoom the affected lines with refresh=true and regenerate the patch.")
        expected = max(0, old_start - 1)
        if expected in matches:
            index = expected
        elif len(matches) == 1:
            index = matches[0]
        else:
            raise ValueError(f"Hunk at line {old_start} matches {len(matches)} locations in '{path}'; "
                             "include more context lines to disambiguate")
        if old_lines and old_lines[-1].endswith(("\n", "\r")) and new_lines \
                and not new_lines[-1].endswith(("\n", "\r")):
            new_lines[-1] += "\n"
        return lines[:index] + new_lines + lines[index + size:]

    def apply_unified_diff(self, patch_text: str):
        """
        Apply a standard git-style unified diff atomically across one or more files.
        Headers must reference existing files that were read with zoom. Every hunk is
        verified in memory first; if any hunk fails, no file is written.
        """
        file_patches = parse_unified_diff(patch_text)
        staged = {}
        for file_path, hunks in file_patches:
            if file_path not in self.snapshots:
                raise ValueError(f"Read '{file_path}' with zoom before applying patch")
            lines = self.text(file_path).splitlines(keepends=True)
            for old_start, old_block, new_block in hunks:
                lines = self._apply_hunk(lines, old_start, old_block, new_block, file_path)
            staged[file_path] = "".join(lines)
        return self.write_batch(staged)

    def blast_radius(self, symbol):
        result = self.search(symbol, limit=40)
        return {"analysis": "literal-reference-approximation", "symbol": symbol,
                "references": result["matches"], "truncated": result["truncated"],
                "note": "Possible references, not resolved callers. Never used to skip final tests."}
