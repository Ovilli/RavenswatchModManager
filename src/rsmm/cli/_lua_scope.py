"""Find Lua reads that compile to a global because their `local` comes later.

The bug this exists for: a closure reads `F`, and `local F = {}` sits 800
lines BELOW it. Lua resolves names lexically, so at the closure `F` is not yet
a local and compiles to a global read — nil at run time, every time. Nothing
says so until the line runs: the LobbyAttributes_Parse detour raised on every
parse, the hook layer disabled it after 20 strikes, and ally names were lost
for the whole session. A steamroller edit later hit the same shape in a mod.

`tests/test_loader_lua.py` catches it for the SDK by reading `luac -l`, but a
player's machine (and the frozen CLI) has no `luac`, so `rsmm lint` needs its
own scope walk. This is that walk: a tokenizer plus a block/scope stack, enough
of Lua to know which names are locals at each point. It reports only the
unambiguous case — a global read of a name the same file declares as a
TOP-LEVEL local further down — so a deliberate global stays silent.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_KEYWORDS = frozenset({
    "and", "break", "do", "else", "elseif", "end", "false", "for", "function",
    "goto", "if", "in", "local", "nil", "not", "or", "repeat", "return", "then",
    "true", "until", "while",
})

#: Lua's own globals. Caching one late (`local pairs = pairs` at the bottom) is
#: odd but harmless, because the earlier reads still find the real global.
_BUILTINS = frozenset({
    "_G", "_ENV", "_VERSION", "assert", "collectgarbage", "coroutine", "debug",
    "dofile", "error", "getmetatable", "io", "ipairs", "load", "loadfile",
    "math", "next", "os", "package", "pairs", "pcall", "print", "rawequal",
    "rawget", "rawlen", "rawset", "require", "select", "setmetatable", "string",
    "table", "tonumber", "tostring", "type", "utf8", "warn", "xpcall",
})

_NAME = re.compile(r"[A-Za-z_]\w*")
_NUMBER = re.compile(
    r"0[xX](?:[0-9a-fA-F]*\.?[0-9a-fA-F]*)(?:[pP][+-]?\d+)?"
    r"|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?")
_OPS = ("...", "..", "::", "==", "~=", "<=", ">=", "//", "<<", ">>")
_LONG_OPEN = re.compile(r"\[(=*)\[")


@dataclass(frozen=True)
class Tok:
    kind: str   # "name" | "kw" | "op" | "str" | "num"
    text: str
    line: int


@dataclass(frozen=True)
class LateLocal:
    """`name` is read on `line` as a global; its top-level local is on `decl_line`."""

    name: str
    line: int
    decl_line: int


class LuaSyntaxError(ValueError):
    """The text is not Lua this walk can follow (unterminated string, …)."""


def tokenize(text: str) -> list[Tok]:
    out: list[Tok] = []
    i, n, line = 0, len(text), 1
    while i < n:
        c = text[i]
        if c == "\n":
            line += 1
            i += 1
        elif c in " \t\r\f\v":
            i += 1
        elif text.startswith("--", i):
            m = _LONG_OPEN.match(text, i + 2)
            if m:
                close = "]" + m.group(1) + "]"
                j = text.find(close, m.end())
                if j < 0:
                    raise LuaSyntaxError(f"line {line}: unterminated long comment")
                line += text.count("\n", i, j)
                i = j + len(close)
            else:
                j = text.find("\n", i)
                i = n if j < 0 else j
        elif c in "\"'":
            j, start = i + 1, line
            while j < n and text[j] != c:
                if text[j] == "\\":
                    if text[j + 1:j + 2] == "\n":
                        line += 1
                    j += 2
                    continue
                if text[j] == "\n":
                    raise LuaSyntaxError(f"line {start}: unterminated string")
                j += 1
            if j >= n:
                raise LuaSyntaxError(f"line {start}: unterminated string")
            out.append(Tok("str", "", start))
            i = j + 1
        elif c == "[" and (m := _LONG_OPEN.match(text, i)):
            close = "]" + m.group(1) + "]"
            j = text.find(close, m.end())
            if j < 0:
                raise LuaSyntaxError(f"line {line}: unterminated long string")
            out.append(Tok("str", "", line))
            line += text.count("\n", i, j)
            i = j + len(close)
        elif (m := _NAME.match(text, i)):
            w = m.group()
            out.append(Tok("kw" if w in _KEYWORDS else "name", w, line))
            i = m.end()
        elif c.isdigit() or (c == "." and text[i + 1:i + 2].isdigit()):
            m = _NUMBER.match(text, i)
            out.append(Tok("num", m.group(), line))
            i = m.end()
        else:
            op = next((o for o in _OPS if text.startswith(o, i)), c)
            out.append(Tok("op", op, line))
            i += len(op)
    return out


class _Walk:
    """One pass over the tokens with a scope stack.

    Scopes are dicts of local name -> token index of its declaration. Each
    scope also remembers the bracket stack it was opened under, because a
    function body inside call arguments (`f(function() ... end)`) starts its
    statements afresh.
    """

    def __init__(self, toks: list[Tok]):
        self.t = toks
        self.scopes: list[dict[str, int]] = [{}]
        self.saved_brackets: list[list[str]] = []
        self.brackets: list[str] = []
        self.pending: list[str] = []          # `for` vars, bound at its `do`
        self.globals: list[tuple[str, int]] = []   # (name, token index)
        self.top_level: dict[str, list[int]] = {}  # name -> decl token indexes

    def at(self, k: int) -> Tok | None:
        return self.t[k] if 0 <= k < len(self.t) else None

    def is_op(self, k: int, text: str) -> bool:
        tok = self.at(k)
        return tok is not None and tok.kind == "op" and tok.text == text

    def declare(self, name: str, k: int) -> None:
        self.scopes[-1][name] = k
        if len(self.scopes) == 1:
            self.top_level.setdefault(name, []).append(k)

    def open(self, *, function: bool = False) -> None:
        self.scopes.append({})
        self.saved_brackets.append(self.brackets)
        self.brackets = [] if function else list(self.brackets)

    def close(self) -> None:
        if len(self.scopes) == 1:
            raise LuaSyntaxError("'end' with no open block")
        self.scopes.pop()
        self.brackets = self.saved_brackets.pop()

    def resolves(self, name: str) -> bool:
        return any(name in s for s in reversed(self.scopes))

    def params(self, k: int) -> int:
        """Bind a parameter list starting at the `(` at `k`; return the index
        after its `)`."""
        if not self.is_op(k, "("):
            raise LuaSyntaxError(f"line {self.t[k - 1].line}: expected '(' after function")
        k += 1
        while not self.is_op(k, ")"):
            tok = self.at(k)
            if tok is None:
                raise LuaSyntaxError("unterminated parameter list")
            if tok.kind == "name":
                self.declare(tok.text, k)
            k += 1
        return k + 1

    def function_body(self, k: int, *, method: bool) -> int:
        self.open(function=True)
        if method:
            self.declare("self", k)
        return self.params(k)

    def run(self) -> None:
        k = 0
        while k < len(self.t):
            k = self.step(k)
        if len(self.scopes) != 1:
            raise LuaSyntaxError("block not closed with 'end'")

    def step(self, k: int) -> int:
        tok = self.t[k]
        if tok.kind == "kw":
            return self.keyword(tok, k)
        if tok.kind == "op":
            if tok.text in "([{":
                self.brackets.append(tok.text)
            elif tok.text in ")]}":
                if self.brackets:
                    self.brackets.pop()
            elif tok.text == "::":           # ::label::
                return k + 3
            return k + 1
        if tok.kind == "name":
            self.name(tok, k)
        return k + 1

    def keyword(self, tok: Tok, k: int) -> int:
        w = tok.text
        if w == "local":
            nxt = self.at(k + 1)
            if nxt is not None and nxt.text == "function":
                fn = self.at(k + 2)
                if fn is None or fn.kind != "name":
                    raise LuaSyntaxError(f"line {tok.line}: bad 'local function'")
                self.declare(fn.text, k + 2)
                return self.function_body(k + 3, method=False)
            k += 1
            while True:
                nm = self.at(k)
                if nm is None or nm.kind != "name":
                    raise LuaSyntaxError(f"line {tok.line}: bad 'local' list")
                self.declare(nm.text, k)
                k += 1
                if self.is_op(k, "<"):            # <const> / <close>
                    k += 3
                if not self.is_op(k, ","):
                    return k
                k += 1
        if w == "function":
            k += 1
            nm = self.at(k)
            method = False
            if nm is not None and nm.kind == "name":
                # `function a.b:c()` READS `a`; `function f()` assigns `f`.
                if self.is_op(k + 1, ".") or self.is_op(k + 1, ":"):
                    self.name(nm, k)
                k += 1
                while self.is_op(k, ".") or self.is_op(k, ":"):
                    method = method or self.t[k].text == ":"
                    k += 2
            return self.function_body(k, method=method)
        if w == "for":
            k += 1
            while (nm := self.at(k)) is not None and nm.kind == "name":
                self.pending.append(nm.text)
                k += 1
                if not self.is_op(k, ","):
                    break
                k += 1
            return k
        if w in ("do", "then", "repeat"):
            self.open()
            if w == "do" and self.pending:
                for name in self.pending:
                    self.scopes[-1][name] = k
                self.pending = []
            return k + 1
        if w in ("else", "elseif"):
            self.close()
            if w == "else":
                self.open()
            return k + 1
        if w in ("end", "until"):
            self.close()
            return k + 1
        if w == "goto":
            return k + 2
        return k + 1

    def name(self, tok: Tok, k: int) -> None:
        prev = self.at(k - 1)
        if prev is not None and prev.kind == "op" and prev.text in (".", ":"):
            return                                   # field / method name
        nxt = self.at(k + 1)
        if (self.brackets and self.brackets[-1] == "{"
                and nxt is not None and nxt.kind == "op" and nxt.text == "="
                and prev is not None and prev.kind == "op" and prev.text in "{,;"):
            return                                   # table key `{ name = ... }`
        if not self.brackets and self.assignment_target(k):
            return                                   # `name = ...` writes, not reads
        if not self.resolves(tok.text):
            self.globals.append((tok.text, k))

    def assignment_target(self, k: int) -> bool:
        """`k` is a plain name in a statement-level target list (`a, b.c = ...`),
        so it is assigned, not read. `a.b = ...` still READS `a`."""
        if not (self.is_op(k + 1, "=") or self.is_op(k + 1, ",")):
            return False
        j, depth = k + 1, 0
        while (tok := self.at(j)) is not None:
            if tok.kind == "op":
                if tok.text == "[":
                    depth += 1
                elif tok.text == "]":
                    depth -= 1
                elif depth == 0 and tok.text == "=":
                    return True
                elif depth == 0 and tok.text not in (",", "."):
                    return False
            elif depth == 0 and tok.kind != "name":
                return False
            j += 1
        return False


def late_locals(text: str) -> list[LateLocal]:
    """Global reads in `text` whose name gets a top-level `local` further down.

    Raises :class:`LuaSyntaxError` when the source is not walkable Lua.
    """
    toks = tokenize(text)
    w = _Walk(toks)
    w.run()
    out: list[LateLocal] = []
    for name, k in w.globals:
        if name in _BUILTINS:
            continue
        later = [d for d in w.top_level.get(name, ()) if d > k]
        if later:
            out.append(LateLocal(name, toks[k].line, toks[later[0]].line))
    return out
