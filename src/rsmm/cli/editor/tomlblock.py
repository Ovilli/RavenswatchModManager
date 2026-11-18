"""Write one ``[[content]]`` block of a manifest back, keeping what did not change.

A hero written from scratch is one block of several hundred lines, most of it
commented by hand (``mods/jack-frame``: ~770). An editor that re-emitted the
whole block on every save would wipe those notes. ``set_block`` instead walks
the block's sections (``[content.frame.abilities.power]``,
``[[content.frame.talents]]`` ...) and touches only what differs:

* a section whose values are unchanged is kept byte for byte, comments included;
* a changed table keeps its header, its comments and its unchanged keys' lines
  (multi-line values too); changed keys are rewritten in place, removed keys
  dropped, new keys added after the last one;
* an array of tables (talents, memoirs, a combo) is kept whole or rewritten
  whole: its elements have no identity to match on;
* a table the old text lacks is inserted after its parent's last section.

The result must parse to exactly the new block with every other block as it
was. When the careful path cannot promise that, the block is emitted afresh
(``emit_block``) and checked the same way; failing both, nothing is written.
"""

from __future__ import annotations

import json
import math
import re
import tomllib

#: Arrays of dicts written as arrays of tables (``[[content.frame.talents]]``):
#: records of their own. Every other list of dicts (hits, layers, steps,
#: add_stats ...) is written inline, as the shipped example mods write them.
AOT_KEYS = frozenset({"talents", "memoirs", "combo"})
#: Dicts down to this depth under the block get a header of their own
#: (``frame`` 1, ``frame.abilities`` 2, ``frame.abilities.power`` 3); deeper
#: ones (an ability's ``indicator``) are inline tables.
TABLE_DEPTH = 3
#: A multi-line value longer than this is not searched for its end.
_MAX_VALUE_LINES = 400

_BARE = re.compile(r"[A-Za-z0-9_-]+\Z")
_HEADER = re.compile(r"^\s*(\[\[?)(.*?)(\]\]?)\s*(#.*)?$")


class BlockError(ValueError):
    """The block cannot be written back faithfully."""


class _Fallback(Exception):
    """The careful rewrite cannot vouch for this block: emit it afresh."""


# --- values -------------------------------------------------------------------

def key(k: str) -> str:
    """``k`` as a TOML key: bare when it can be, quoted otherwise."""
    return k if _BARE.match(k) else json.dumps(k, ensure_ascii=False)


def value(v) -> str:
    """One TOML value on one line."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        if not math.isfinite(v):
            raise BlockError(f"no TOML form for {v!r}")
        return repr(v)
    if isinstance(v, str):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        return "[" + ", ".join(value(x) for x in v) + "]"
    if isinstance(v, dict):
        if not v:
            return "{}"
        return "{ " + ", ".join(f"{key(str(k))} = {value(x)}" for k, x in v.items()) + " }"
    raise BlockError(f"no TOML form for {v!r}")


def _assign(k: str, v, pad: int = 0) -> list[str]:
    """``k = v`` as lines: a long list of tables one element per line."""
    head = f"{key(k):<{pad}} = " if pad else f"{key(k)} = "
    one = head + value(v)
    if (isinstance(v, list) and len(v) > 1 and all(isinstance(x, dict) for x in v)
            and len(one) > 100):
        return [head + "[\n", *(f"  {value(x)},\n" for x in v), "]\n"]
    return [one + "\n"]


def _same(a, b) -> bool:
    """``a`` and ``b`` would be written alike: equal, a bool never a number
    (``True == 1`` in Python), an int and a float equal when their numbers are
    (the page cannot tell ``6`` from ``6.0``)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return a == b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y) for x, y in zip(a, b, strict=True))
    return type(a) is type(b) and a == b


def _clean(v):
    """``v`` with ``None`` values dropped (the page's way of saying "unset")."""
    if isinstance(v, dict):
        return {str(k): _clean(x) for k, x in v.items() if x is not None}
    if isinstance(v, list):
        return [_clean(x) for x in v if x is not None]
    return v


# --- which values are sections --------------------------------------------------

def _get(d, path: tuple):
    for p in path:
        if not isinstance(d, dict) or p not in d:
            return None
        d = d[p]
    return d


def _aot(path: tuple, v) -> bool:
    return (bool(path) and path[-1] in AOT_KEYS and len(path) <= TABLE_DEPTH + 1
            and isinstance(v, list) and bool(v) and all(isinstance(x, dict) for x in v))


def _table(path: tuple, v) -> bool:
    return isinstance(v, dict) and 1 <= len(path) <= TABLE_DEPTH


def _rule(path: tuple, v) -> str | None:
    """How a fresh emit writes ``v`` at ``path``: "table", "aot" or inline (None)."""
    if _aot(path, v):
        return "aot"
    if _table(path, v):
        return "table"
    return None


def _inline(d: dict, path: tuple, sec) -> dict:
    return {k: v for k, v in d.items() if sec((*path, k), v) is None}


# --- emitting ---------------------------------------------------------------------

def _header(path: tuple, aot: bool) -> str:
    name = ".".join(key(p) for p in ("content", *path))
    return f"[[{name}]]\n" if aot else f"[{name}]\n"


def _emit(path: tuple, d: dict, sec, done: set | None = None) -> list[str]:
    """Lines for the table ``d`` at ``path`` and every section below it (those
    in ``done`` excepted: they are already in the text)."""
    out: list[str] = []
    inline = _inline(d, path, sec)
    children = [(k, v) for k, v in d.items() if sec((*path, k), v) is not None]
    if inline or not children:
        out += ["\n", _header(path, False)]
        for k, v in inline.items():
            out += _assign(k, v)
    for k, v in children:
        p = (*path, k)
        if done is not None and p in done:
            continue
        if sec(p, v) == "aot":
            out += _emit_aot(p, v)
        else:
            out += _emit(p, v, sec, done)
    return out


def _emit_aot(path: tuple, items: list) -> list[str]:
    out: list[str] = []
    for el in items:
        out += ["\n", _header(path, True)]
        for k, v in el.items():
            out += _assign(k, v)
    return out


def emit_block(block: dict) -> str:
    """The whole block, freshly written (no comments)."""
    block = _clean(block)
    lines = ["[[content]]\n"]
    inline = _inline(block, (), _rule)
    pad = max((len(key(k)) for k in inline), default=0)
    for k, v in inline.items():
        lines += _assign(k, v, pad)
    for k, v in block.items():
        p = (k,)
        kind = _rule(p, v)
        if kind == "aot":
            lines += _emit_aot(p, v)
        elif kind == "table":
            lines += _emit(p, v, _rule)
    return "".join(lines)


# --- reading the old text -----------------------------------------------------------

def _scan(line: str, state: list) -> tuple[int, int]:
    """Bracket depth change of ``line`` outside strings, and where a trailing
    comment starts (-1 if none). ``state[0]`` carries an open multi-line string
    (its delimiter) from line to line."""
    depth, i, n = 0, 0, len(line)
    while i < n:
        s = state[0]
        if s:
            if s in ('"""', "'''"):
                j = line.find(s, i)
                if j < 0:
                    return depth, -1
                state[0], i = "", j + 3
                continue
            # a basic or literal string never spans lines
            j = i
            while j < n and line[j] != s:
                j += 2 if (s == '"' and line[j] == "\\") else 1
            state[0], i = "", j + 1
            continue
        c = line[i]
        if c == "#":
            return depth, i
        if line.startswith(('"""', "'''"), i):
            state[0], i = line[i:i + 3], i + 3
            continue
        if c in "\"'":
            state[0], i = c, i + 1
            continue
        if c in "[{":
            depth += 1
        elif c in "]}":
            depth -= 1
        i += 1
    return depth, -1


def _split_key(text: str) -> tuple:
    """A dotted header name (``content.frame.ultimates."Ultimate Power 1"``) as a path."""
    parts, i, n = [], 0, len(text)
    while i < n:
        while i < n and text[i] in " \t":
            i += 1
        if i < n and text[i] in "\"'":
            q = text[i]
            j = i + 1
            while j < n and text[j] != q:
                j += 2 if (q == '"' and text[j] == "\\") else 1
            raw = text[i:j + 1]
            parts.append(json.loads(raw) if q == '"' else raw[1:-1])
            i = j + 1
        else:
            j = i
            while j < n and text[j] not in ". \t":
                j += 1
            parts.append(text[i:j])
            i = j
        while i < n and text[i] in " \t":
            i += 1
        if i < n and text[i] == ".":
            i += 1
    return tuple(parts)


def _headers(lines: list[str]) -> list[tuple[int, tuple, bool]]:
    """``(line, path, is an array table)`` of every header outside a value."""
    out, depth, state = [], 0, [""]
    for i, line in enumerate(lines):
        if depth == 0 and not state[0]:
            m = _HEADER.match(line)
            if m and (m.group(1) == "[[") == (m.group(3) == "]]") and m.group(2).strip():
                out.append((i, _split_key(m.group(2)), m.group(1) == "[["))
                continue
        d, _c = _scan(line, state)
        depth = max(0, depth + d)
    return out


def _attached(lines: list[str], i: int, floor: int) -> int:
    """First line of the comment run directly above line ``i`` (not above ``floor``)."""
    while i > floor and lines[i - 1].lstrip().startswith("#"):
        i -= 1
    return i


def _content(text: str) -> list:
    try:
        return [c for c in tomllib.loads(text).get("content", []) if isinstance(c, dict)]
    except tomllib.TOMLDecodeError as e:
        raise BlockError(f"manifest.toml does not parse: {e}") from e


def _find(lines: list[str], heads: list, kind: str, block_id: str) -> tuple[int, int, int]:
    """``(first header index, start line, end line)`` of the block."""
    found = None
    for n, (i, path, aot) in enumerate(heads):
        if not (aot and path == ("content",)):
            continue
        nxt = next((j for j, p, a in heads[n + 1:] if p[:1] != ("content",)
                    or (a and p == ("content",))), len(lines))
        end = _attached(lines, nxt, i) if nxt < len(lines) else nxt
        try:
            got = tomllib.loads("".join(lines[i:end])).get("content", [{}])[0]
        except tomllib.TOMLDecodeError:
            continue
        if got.get("kind") == kind and got.get("id") == block_id:
            if found is not None:
                raise BlockError(f"manifest.toml has two {kind} blocks with id {block_id!r}")
            found = (n, i, end)
    if found is None:
        raise BlockError(f"no {kind} block {block_id!r} in manifest.toml")
    return found


# --- the careful rewrite ----------------------------------------------------------------

def _kv_spans(lines: list[str], lo: int, hi: int) -> list[tuple[str, int, int, object]]:
    """``(top key, first line, end line, its value)`` of each assignment in
    ``lines[lo:hi]`` (a section's body)."""
    spans, j = [], lo
    while j < hi:
        s = lines[j].strip()
        if not s or s.startswith("#"):
            j += 1
            continue
        for end in range(j + 1, min(hi, j + _MAX_VALUE_LINES) + 1):
            try:
                got = tomllib.loads("".join(lines[j:end]))
            except tomllib.TOMLDecodeError:
                continue
            break
        else:
            raise _Fallback
        if len(got) != 1:
            raise _Fallback
        k, v = next(iter(got.items()))
        if spans and any(sk == k for sk, *_ in spans):
            raise _Fallback                 # dotted keys spread over lines
        if isinstance(v, dict) and re.match(r"\s*[^=]*\.", lines[j].split("=", 1)[0]):
            raise _Fallback                 # `a.b = 1`: not a key the page writes
        spans.append((k, j, end, v))
        j = end
    return spans


def _pad_of(lines: list[str], spans) -> int:
    """The column an aligned section's ``=`` sits at (0 when not aligned)."""
    for _k, j, _e, _v in spans:
        m = re.match(r"\s*(\S+?)(\s+)=", lines[j])
        if m and len(m.group(2)) > 1:
            return len(m.group(1)) + len(m.group(2)) - 1
    return 0


def _patch(lines: list[str], h: int, hi: int, old: dict, new: dict) -> list[str]:
    """The section whose header is line ``h`` (body to ``hi``), its keys made
    ``new`` (its inline part), unchanged lines kept."""
    spans = _kv_spans(lines, h + 1, hi)
    pad = _pad_of(lines, spans)
    old_keys = {k for k, *_ in spans}
    out, j = [lines[h]], h + 1
    last = len(out)                         # where new keys go
    by_start = {s[1]: s for s in spans}
    while j < hi:
        if j not in by_start:
            out.append(lines[j])
            j += 1
            continue
        k, a, b, ov = by_start[j]
        if k in new:
            if _same(new[k], ov):
                out += lines[a:b]
            else:
                text = _assign(k, new[k], pad)
                if b - a == 1 and len(text) == 1:
                    _d, c = _scan(lines[a], [""])
                    if c >= 0:
                        text = [text[0].rstrip("\n") + "   " + lines[a][c:].rstrip("\n") + "\n"]
                    indent = lines[a][:len(lines[a]) - len(lines[a].lstrip())]
                    text = [indent + text[0]]
                out += text
            last = len(out)
        j = b
    add = [ln for k, v in new.items() if k not in old_keys for ln in _assign(k, v, pad)]
    return out[:last] + add + out[last:]


def _ident(items: list) -> str | None:
    """The field that names an array-of-tables element (a talent's ``name``, a
    memoir's ``title``), when every element has a distinct one."""
    for f in ("name", "title", "id"):
        vals = [x.get(f) for x in items if isinstance(x, dict)]
        if vals and all(isinstance(v, str) and v for v in vals) and len(set(vals)) == len(vals):
            return f
    return None


def _rewrite(lines: list[str], heads: list, n0: int, start: int, end: int,
             old: dict, new: dict) -> str:
    """The block ``lines[start:end]`` rewritten to ``new``, keeping what it can."""
    inner = [(i, p[1:], a) for i, p, a in heads[n0:] if start <= i < end]
    old_sections = {p for _i, p, _a in inner}
    old_aots = {p for _i, p, a in inner if a and p}
    implicit = {q[:n] for q in old_sections for n in range(1, len(q))}

    def sec(path: tuple, v) -> str | None:
        """How ``v`` at ``path`` is written: as the old text wrote it (a header
        of its own, or inline in its parent), else as a fresh emit would."""
        if path in old_aots:
            return "aot" if (isinstance(v, list) and v
                             and all(isinstance(x, dict) for x in v)) else None
        if path in old_sections or path in implicit:
            return "table" if isinstance(v, dict) else None
        if _get(old, path) is not None:
            return None                     # written inline before: stays inline
        return _rule(path, v)

    # Each section's span: its header to the next header's attached comment.
    sections = []
    for k, (i, p, a) in enumerate(inner):
        nxt = inner[k + 1][0] if k + 1 < len(inner) else end
        hi = _attached(lines, nxt, i) if k + 1 < len(inner) else end
        lo = start if k == 0 else sections[-1][2]
        sections.append((p, a, hi, lo, i))

    def owner(p: tuple) -> tuple | None:
        """The array of tables ``p`` sits in (itself, or an element's sub-table)."""
        return next((p[:n] for n in range(1, len(p) + 1) if p[:n] in old_aots), None)

    groups: dict[tuple, list] = {}
    for s in sections:
        if (g := owner(s[0])) is not None:
            groups.setdefault(g, []).append(s)

    chunks: list[tuple[tuple, list[str]]] = []
    done: set[tuple] = set()                # paths the new text holds
    for p, _a, hi, lo, h in sections:
        grp = owner(p)
        if grp is not None:
            if grp in done:
                continue
            done.add(grp)
            chunks += _rewrite_aot(lines, grp, groups[grp], _get(old, grp), _get(new, grp),
                                   sec(grp, _get(new, grp)) == "aot")
            continue
        nv = _get(new, p) if p else new
        if p and sec(p, nv) != "table":
            continue                        # gone, or now written inline in its parent
        ov = _get(old, p) if p else old
        if not isinstance(ov, dict):
            raise _Fallback
        body = _patch(lines, h, hi, ov, _inline(nv, p, sec))
        chunks.append((p, lines[lo:h] + body))
        done.add(p)

    # Sections the old text lacks, each after its parent's last section.
    def mark(path: tuple, d: dict) -> None:
        for k, v in d.items():
            q = (*path, k)
            if sec(q, v) is not None:
                done.add(q)
                if isinstance(v, dict):
                    mark(q, v)

    def missing(path: tuple, d: dict) -> None:
        for k, v in d.items():
            q = (*path, k)
            kind = sec(q, v)
            if kind is None:
                continue
            if q in done:
                if kind == "table":
                    missing(q, v)
                continue
            if kind == "aot":
                text = _emit_aot(q, v)
            else:
                text = _emit(q, v, sec, done)
                mark(q, v)
            done.add(q)
            parent = q[:-1]
            at = max((n for n, (cp, _l) in enumerate(chunks) if cp[:len(parent)] == parent),
                     default=len(chunks) - 1)
            chunks.insert(at + 1, (q, text))

    missing((), new)
    out: list[str] = []
    for _p, ls in chunks:
        if not ls:
            continue
        if ls[0] == "\n" and (not out or not out[-1].strip()):
            ls = ls[1:]                     # a fresh section's blank line, already there
        if ls and not ls[-1].endswith("\n"):
            ls = [*ls[:-1], ls[-1] + "\n"]
        out += ls
    return "".join(out)


def _rewrite_aot(lines: list[str], grp: tuple, secs: list, old_items, new_items,
                 is_aot: bool) -> list[tuple[tuple, list[str]]]:
    """An array of tables, element by element: an element the new list still
    has (same name, else same place) keeps its lines and comments, patched
    where it changed; a new one is emitted; a dropped one goes."""
    if _same(old_items, new_items):
        return [(s[0], lines[s[3]:s[2]]) for s in secs]
    if not is_aot:
        return []
    elems = [s for s in secs if s[0] == grp]
    if len(elems) != len(secs) or not isinstance(old_items, list) \
            or len(old_items) != len(elems):
        lead = lines[secs[0][3]:secs[0][4]]
        return [(grp, lead + _emit_aot(grp, new_items)[1 if lead else 0:] + ["\n"])]
    f = _ident(old_items) if _ident(new_items) == _ident(old_items) else None
    unused = list(range(len(old_items)))
    pairs: list[int | None] = []
    for j, el in enumerate(new_items):
        hit = None
        if f is not None:
            hit = next((i for i in unused if old_items[i].get(f) == el.get(f)), None)
        elif j in unused and len(new_items) == len(old_items):
            hit = j
        if hit is not None:
            unused.remove(hit)
        pairs.append(hit)
    out = []
    for j, el in enumerate(new_items):
        i = pairs[j]
        if i is None:
            out.append((grp, _emit_aot(grp, [el])))
            continue
        _p, _a, hi, lo, h = elems[i]
        out.append((grp, lines[lo:h] + _patch(lines, h, hi, old_items[i], el)))
    return out


def set_block(text: str, kind: str, block_id: str, block: dict) -> str:
    """``text`` with the ``kind`` block ``block_id`` made ``block`` (which may
    carry a new ``id``), every untouched line kept. Raises :class:`BlockError`
    unless the result parses to exactly that change."""
    block = _clean(block)
    if block.get("kind") != kind:
        raise BlockError(f"the block must stay kind = {kind!r}")
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    heads = _headers(lines)
    n0, start, end = _find(lines, heads, kind, block_id)
    want = [block if c.get("kind") == kind and c.get("id") == block_id else c
            for c in _content(text)]
    old = tomllib.loads("".join(lines[start:end]))["content"][0]
    tail = lines[end:]
    blank = 0                               # the blank lines after the block, as they were
    while blank < end - start and not lines[end - 1 - blank].strip():
        blank += 1
    sep = "\n" * (blank or (1 if tail else 0))
    try:
        body = _rewrite(lines, heads, n0, start, end, old, block)
        new = "".join(lines[:start]) + body.rstrip("\n") + "\n" + sep + "".join(tail)
        if _content(new) == want:
            return new
    except (_Fallback, BlockError, tomllib.TOMLDecodeError):
        pass
    new = "".join(lines[:start]) + emit_block(block).rstrip("\n") + "\n" + sep + "".join(tail)
    try:
        ok = _content(new) == want
    except BlockError:
        ok = False
    if not ok:
        raise BlockError("could not write the block back cleanly; edit manifest.toml by hand")
    return new


def add_block(text: str, block: dict) -> str:
    """``text`` with ``block`` appended. Refuses an id its kind already uses."""
    block = _clean(block)
    before = _content(text)
    if any(c.get("kind") == block.get("kind") and c.get("id") == block.get("id")
           for c in before):
        raise BlockError(f"manifest.toml already has a {block.get('kind')} block with id "
                         f"{block.get('id')!r}")
    new = text.rstrip("\n") + "\n\n" + emit_block(block)
    if _content(new) != [*before, block]:
        raise BlockError("could not add the block to manifest.toml cleanly; add it by hand")
    return new
