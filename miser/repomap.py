"""Repository map from a definition/reference graph ranked by standard-library PageRank.

The graph follows Aider's approach: file nodes are connected through the identifiers they
define and reference, weights favour distinctive identifiers and files named in the task,
and PageRank spreads importance towards files the rest of the repository leans on. This is
an approximation, not a resolved call graph: references are identifier occurrences, not
resolved bindings.
"""

import json
import math
import os
import re
from collections import Counter
from pathlib import Path

IDENTIFIER = re.compile(r"[A-Za-z_$][A-Za-z0-9_$]*")
PY_SUFFIXES = (".py",)
JS_SUFFIXES = (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")

# Language keywords add no graph signal; keeping them out keeps rank focused on symbols.
STOPWORDS = {
    "the", "and", "for", "with", "that", "this", "from", "into", "are", "was", "were",
    "will", "would", "should", "could", "have", "has", "had", "not", "but", "you",
    "self", "super", "true", "false", "none", "null", "undefined", "true", "false",
    "and", "or", "not", "if", "else", "elif", "for", "while", "return", "def", "class",
    "import", "from", "as", "with", "try", "except", "finally", "raise", "pass", "break",
    "continue", "lambda", "yield", "in", "is", "const", "let", "var", "function", "async",
    "await", "new", "typeof", "instanceof", "export", "default", "extends", "static",
    "public", "private", "protected", "readonly", "interface", "type", "enum", "void",
    "string", "number", "boolean", "any", "unknown", "never", "print", "len", "str", "int",
    "list", "dict", "set", "tuple", "range", "open", "json", "os", "sys", "re", "path",
}

CACHE_VERSION = 2


def pagerank(nodes, edges, personalization=None, damping=0.85, iterations=100,
             tolerance=1e-10):
    """Weighted PageRank over `nodes` with directed `edges` {(src, dst): weight}.

    Standard-library implementation: no networkx dependency. Dangling nodes distribute
    their mass through the personalization vector so isolated files cannot trap rank.
    """
    nodes = sorted(nodes)
    if not nodes:
        return {}
    out = {node: {} for node in nodes}
    for (source, target), weight in edges.items():
        if weight > 0 and source in out and target in out:
            out[source][target] = out[source].get(target, 0.0) + weight

    if personalization:
        total = sum(personalization.get(node, 0.0) for node in nodes)
        if total <= 0:
            personalization = None
    if personalization:
        # Unlisted nodes still receive a small share so every file stays reachable.
        base = 1.0 / (len(nodes) * 1000)
        pers = {node: personalization.get(node, 0.0) / total + base for node in nodes}
        pers_total = sum(pers.values())
        pers = {node: value / pers_total for node, value in pers.items()}
    else:
        pers = {node: 1.0 / len(nodes) for node in nodes}

    rank = {node: 1.0 / len(nodes) for node in nodes}
    dangling = [node for node in nodes if not out[node]]
    for _ in range(iterations):
        new = {node: (1 - damping) * pers[node] for node in nodes}
        dangling_mass = sum(rank[node] for node in dangling)
        for node in nodes:
            destinations = out[node]
            if not destinations:
                continue
            total_weight = sum(destinations.values())
            share = damping * rank[node] / total_weight
            for target, weight in destinations.items():
                new[target] += share * weight
        if dangling_mass:
            for node in nodes:
                new[node] += damping * dangling_mass * pers[node]
        delta = sum(abs(new[node] - rank[node]) for node in nodes)
        rank = new
        if delta < tolerance:
            break
    return rank


def identifier_weight(ident, mentioned):
    """Aider-style weight: distinctive and task-relevant identifiers dominate noise."""
    weight = 1.0
    snake = "_" in ident and any(char.isalpha() for char in ident)
    camel = any(char.isupper() for char in ident) and any(char.islower() for char in ident)
    if ident.lower() in mentioned:
        weight *= 10
    if (snake or camel) and len(ident) >= 8:
        weight *= 10
    if ident.startswith("_"):
        weight *= 0.1
    return weight


def query_terms(query):
    """Lowercase task terms used for personalization and identifier weighting."""
    return {term for term in IDENTIFIER.findall(query.lower())
            if len(term) >= 3 and term not in STOPWORDS}


class RepoMap:
    """Build a task-ranked repository map from a cached definition/reference graph."""

    MAX_FILES = 600
    MAX_SOURCE_BYTES = 1_500_000
    MAX_REFS_PER_FILE = 120

    def __init__(self, workspace):
        self.workspace = workspace
        self.root = Path(workspace.root)
        self.cache_path = self.root / ".miser" / "cache" / "repomap.json"

    # -- cache ---------------------------------------------------------------

    def _load_cache(self):
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
        except (OSError, ValueError, UnicodeError):
            return {"version": CACHE_VERSION, "files": {}}
        if not isinstance(data, dict) or data.get("version") != CACHE_VERSION \
                or not isinstance(data.get("files"), dict):
            return {"version": CACHE_VERSION, "files": {}}
        return data

    def _save_cache(self, data):
        try:
            self.cache_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.cache_path.with_suffix(".json.tmp")
            temp.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                            encoding="utf-8")
            os.replace(temp, self.cache_path)
        except OSError:
            # A read-only checkout must not break the map; the cache is an optimization.
            pass

    # -- extraction ----------------------------------------------------------

    def _select_files(self, terms):
        """Bound the scanned corpus: task-named paths first, then shallow project files."""
        names = self.workspace.files()
        candidates = []
        for name in names:
            path = self.workspace.root / name
            try:
                size = path.stat().st_size
            except OSError:
                continue
            if size > 250_000:
                continue
            lowered = name.lower()
            matches = sum(term in lowered for term in terms)
            candidates.append((matches, name.count("/"), name, size))
        candidates.sort(key=lambda item: (-item[0], item[1], item[2]))
        selected, total = [], 0
        for _matches, _depth, name, size in candidates:
            if len(selected) >= self.MAX_FILES or total + size > self.MAX_SOURCE_BYTES:
                break
            selected.append(name)
            total += size
        return selected

    def _extract(self, name, text, cached):
        """Definitions plus bounded reference counts for one file."""
        try:
            stat = (self.root / name).stat()
        except OSError:
            return None
        key = f"{stat.st_mtime_ns}:{stat.st_size}"
        if cached and cached.get("key") == key and isinstance(cached.get("defs"), list) \
                and isinstance(cached.get("refs"), dict):
            # Keep the in-memory symbol cache warm for zoom/repo-map consumers.
            self.workspace.symbols(name, text)
            return cached["defs"], cached["refs"], key
        symbols = self.workspace.symbols(name, text)
        defs = [[symbol["name"], symbol["line"]] for symbol in symbols]
        counts = Counter(token for token in IDENTIFIER.findall(text)
                         if len(token) >= 2 and token.lower() not in STOPWORDS)
        refs = dict(counts.most_common(self.MAX_REFS_PER_FILE))
        return defs, refs, key

    # -- graph ---------------------------------------------------------------

    def build(self, query="", max_chars=4000):
        terms = query_terms(query)
        names = self._select_files(terms)
        cache = self._load_cache()
        files_cache = cache["files"]
        texts = {}
        defs, refs, keys = {}, {}, {}
        for name in names:
            try:
                text = self.workspace.text(name)
            except (OSError, ValueError, UnicodeError):
                continue
            extracted = self._extract(name, text, files_cache.get(name))
            if extracted is None:
                continue
            texts[name] = text
            defs[name], refs[name], keys[name] = extracted

        # Persist only current files so the cache cannot grow without bound; each entry is
        # validated by mtime_ns:size, so an edited file is re-parsed on the next map.
        fresh_cache = {name: {"key": keys[name], "defs": defs[name], "refs": refs[name]}
                       for name in texts}
        if fresh_cache != files_cache:
            cache["files"] = fresh_cache
            self._save_cache(cache)

        if not texts:
            return {"analysis": "pagerank-reference-graph", "entries": [], "truncated": False,
                    "note": "No readable source files in the workspace."}

        definers = {}
        for name, entries in defs.items():
            for symbol, line in entries:
                definers.setdefault(symbol, {}).setdefault(name, set()).add(line)

        edges = {}
        out_edges = {}
        referenced = set()
        for name, counts in refs.items():
            parts = set(Path(name).parts) | {Path(name).stem}
            for ident, count in counts.items():
                if ident not in definers:
                    continue
                weight = identifier_weight(ident, terms) * math.sqrt(count)
                if len(definers[ident]) > 5:
                    weight *= 0.1
                if terms & parts:
                    weight *= 50
                for definer in definers[ident]:
                    share = weight / len(definers[ident])
                    edges[(name, definer)] = edges.get((name, definer), 0.0) + share
                    out_edges.setdefault(name, []).append((definer, ident, share))
                    referenced.add((name, definer))

        # Files defining something nobody references still deserve a small anchor.
        referencers = {source for source, _target in referenced}
        for ident, definer_files in definers.items():
            for definer in definer_files:
                if definer in referencers:
                    continue
                edges[(definer, definer)] = edges.get((definer, definer), 0.0) + 0.1
                out_edges.setdefault(definer, []).append((definer, ident, 0.1))

        personalization = {}
        for name in texts:
            parts = set(Path(name).parts) | {Path(name).stem}
            if terms & parts:
                personalization[name] = personalization.get(name, 0.0) + 100.0 / len(texts)
        rank = pagerank(texts, edges, personalization)

        ranked_defs = {}
        for source, destinations in out_edges.items():
            total = sum(weight for _dst, _ident, weight in destinations)
            if not total:
                continue
            source_rank = rank.get(source, 0.0)
            for dst, ident, weight in destinations:
                ranked_defs[(dst, ident)] = ranked_defs.get((dst, ident), 0.0) + \
                    source_rank * weight / total

        # A definition whose own name echoes the task is the strongest local signal.
        def definition_bonus(ident):
            lowered = ident.lower()
            return 1.0 + 3.0 * sum(term in lowered for term in terms)

        # File priority comes from graph centrality; a task-named definition lifts its file.
        file_scores = {}
        for name in texts:
            bonuses = [definition_bonus(symbol) for symbol, _line in defs[name]]
            file_scores[name] = rank.get(name, 0.0) * max(bonuses, default=1.0)

        def path_matches(name):
            # Exact path-component or file-stem matches, not substrings of arbitrary words.
            parts = set(Path(name).parts) | {Path(name).stem}
            return len(terms & parts)

        def priority(name):
            # A task term in the path is a reliable relevance signal; exact components only.
            return file_scores.get(name, 0.0) * (1.0 + 2.0 * path_matches(name))

        ordered = sorted(texts, key=lambda name: (-priority(name), -path_matches(name), name))
        entries = []
        result = {"analysis": "pagerank-reference-graph", "entries": entries, "truncated": False,
                  "note": "PageRank over identifier definitions/references; an approximation, "
                          "not a resolved call graph. Zoom before editing."}
        for name in ordered:
            symbols = sorted(defs[name], key=lambda item: (
                -ranked_defs.get((name, item[0]), 0.0), item[1]))[:8]
            entry = {"path": name}
            if symbols:
                entry["symbols"] = [{"name": symbol, "line": line} for symbol, line in symbols]
            entries.append(entry)
            if len(json.dumps(result, ensure_ascii=False)) > max_chars - 30:
                entries.pop()
                break
        result["truncated"] = len(entries) < len(texts)
        result["included_files"] = len(texts)
        return result
