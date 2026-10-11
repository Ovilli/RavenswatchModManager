"""The Scripts tab's block program, turned into Lua.

The page edits a Blockly workspace and sends its saved state (Blockly's own
JSON). This module is the only thing that turns that state into code, on
purpose: the page never ships Lua, so a program can only do what a block here
knows how to say. Every block type is on the whitelist below, every name that
reaches the source passes ``_NAME_RE``, and every game call is a high-level
``R.*`` function -- the same rule ``rsmm lint`` holds a mod's own Lua to (no
addresses, no ``_internal``, no raw memory).

An unknown block, a call to a function nothing defines, or a program past the
size limits is an ``EditorError``: the editor reports it and writes nothing.

The result is one marked section of ``init.lua`` (see ``modio.write_blocks``)
that carries the workspace state in a comment, so the page can open it again.
"""

from __future__ import annotations

import json
import math
import re

from .content import EditorError

#: Names that may reach the Lua source as a string: item ids, talents, stats,
#: heroes. Nothing in the set needs escaping.
_NAME_RE = re.compile(r"^[A-Za-z0-9 _'.\-]{1,64}$")
_EVENT_RE = re.compile(r"^[A-Z0-9_]{2,64}$")

MAX_BLOCKS = 2000
MAX_DEPTH = 64
MAX_TEXT = 500
MAX_REPEAT = 1000          # a repeat or for block never loops more often than this
MAX_WHILE = 10000          # a while block stops after this many turns
MAX_COUNT = 99
MIN_SECONDS = 0.05

#: Events a hat block can listen to: label shown by the page -> R.on name.
LIFECYCLE = {"run:start": "a run starts", "run:end": "a run ends",
             "menu:enter": "the menu opens", "ready": "the game is ready"}

_HP_ACTIONS = {"heal": "R.hp.heal", "damage": "R.hp.damage", "set": "R.hp.set"}
_SHARD_ACTIONS = {"add": "R.shards.add", "spend": "R.shards.spend", "set": "R.shards.set"}
_HP_READS = {"hp": "R.hp.get()", "max": "R.hp.max()", "frac": "R.hp.frac()"}
_COMPARE = {"EQ": "==", "NEQ": "~=", "LT": "<", "LTE": "<=", "GT": ">", "GTE": ">="}
_ARITH = {"ADD": "+", "MINUS": "-", "MULTIPLY": "*", "DIVIDE": "/", "POWER": "^"}
_WHERE = {"FROM_START", "FROM_END", "FIRST", "LAST", "RANDOM"}
_NUMPROPS = {"EVEN", "ODD", "PRIME", "WHOLE", "POSITIVE", "NEGATIVE", "DIVISIBLE_BY"}

BEGIN = "-- >>> rsmm editor: blocks >>>"
END = "-- <<< rsmm editor: blocks <<<"
CONFIG = "-- editor-blocks: "


def empty_state() -> dict:
    return {"blocks": {"languageVersion": 0, "blocks": []}, "variables": []}


def _lstr(s: str) -> str:
    """``s`` as a Lua string literal."""
    out = []
    for ch in s:
        if ch in '"\\':
            out.append("\\" + ch)
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ord(ch) < 32:
            out.append(f"\\{ord(ch):03d}")
        else:
            out.append(ch)
    return '"' + "".join(out) + '"'


def _num(v, what: str) -> str:
    if isinstance(v, bool) or not isinstance(v, int | float) or not math.isfinite(v):
        raise EditorError(f"{what}: a number is needed")
    return repr(int(v)) if float(v).is_integer() and abs(v) < 1e15 else repr(float(v))


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]", "_", name)[:32] or "x"


class _Compiler:
    def __init__(self, state: dict):
        self.uses: set[str] = set()         # which helper prelude pieces the program needs
        self.warnings: list[str] = []
        self.count = 0
        self.var_names: dict[str, str] = {}   # Blockly variable id -> Lua name
        self.globals: list[str] = []
        self.procs: dict[str, dict] = {}      # procedure name -> {lua, params, returns}
        self.loops: list[dict] = []           # the loops around the block being written
        self.labels = 0
        self.state = state

    # -- structure ---------------------------------------------------------------

    def compile(self) -> list[str]:
        ws = self.state.get("blocks") or {}
        tops = ws.get("blocks") or []
        if not isinstance(tops, list):
            raise EditorError("the block program is not a list of blocks")
        self._variables(tops)
        defs = [b for b in tops if b.get("type") in ("procedures_defnoreturn",
                                                      "procedures_defreturn")]
        for d in defs:
            self._declare_proc(d)
        handlers, funcs, loose = [], [], 0
        for b in tops:
            if b.get("enabled") is False:
                continue
            t = b.get("type")
            if t in ("procedures_defnoreturn", "procedures_defreturn"):
                funcs.append(self._proc(b))
            elif t in ("rsmm_on_event", "rsmm_on_gameplay", "rsmm_on_every"):
                handlers.append(self._handler(b))
            else:
                loose += 1
        if loose:
            self.warnings.append(
                f"{loose} block(s) are not under an event or a function and do nothing")
        if self.count > MAX_BLOCKS:
            raise EditorError(f"the program has {self.count} blocks; the limit is {MAX_BLOCKS}")
        lines: list[str] = []
        if self.globals:
            lines += [f"local {n} = 0" for n in self.globals]
        if self.procs:
            lines.append("local " + ", ".join(p["lua"] for p in self.procs.values()))
        for f in funcs:
            lines += f
        for h in handlers:
            lines += h
        return lines

    def _variables(self, tops: list) -> None:
        params: set[str] = set()
        for b in tops:
            if b.get("type") in ("procedures_defnoreturn", "procedures_defreturn"):
                for p in (b.get("extraState") or {}).get("params") or []:
                    if isinstance(p, dict) and p.get("id"):
                        params.add(p["id"])
        used: set[str] = set()

        def unique(base: str) -> str:
            name, i = base, 1
            while name in used:
                i += 1
                name = f"{base}_{i}"
            used.add(name)
            return name

        for v in self.state.get("variables") or []:
            if not isinstance(v, dict) or not v.get("id"):
                continue
            nm = str(v.get("name") or "")
            if v["id"] in params:
                self.var_names[v["id"]] = unique("p_" + _slug(nm))
            else:
                lua = unique("v_" + _slug(nm))
                self.var_names[v["id"]] = lua
                self.globals.append(lua)
        for b in tops:       # a parameter the variable list did not carry
            if b.get("type") in ("procedures_defnoreturn", "procedures_defreturn"):
                for p in (b.get("extraState") or {}).get("params") or []:
                    if isinstance(p, dict) and p.get("id") and p["id"] not in self.var_names:
                        self.var_names[p["id"]] = unique("p_" + _slug(str(p.get("name") or "")))

    def _declare_proc(self, b: dict) -> None:
        name = str((b.get("fields") or {}).get("NAME") or "")
        if not name or len(name) > 64:
            raise EditorError("a function needs a name (64 characters at most)")
        if name in self.procs:
            raise EditorError(f"two functions are called {name!r}")
        params = [p for p in (b.get("extraState") or {}).get("params") or []
                  if isinstance(p, dict)]
        self.procs[name] = {"lua": f"f_{_slug(name)}_{len(self.procs)}",
                            "params": [self.var_names.get(p.get("id"), "p_" + _slug(
                                str(p.get("name") or ""))) for p in params],
                            "returns": b["type"] == "procedures_defreturn"}

    def _proc(self, b: dict) -> list[str]:
        name = b["fields"]["NAME"]
        info = self.procs[name]
        self.count += 1
        body = self._chain((b.get("inputs") or {}).get("STACK"), 1, 0)
        if info["returns"]:
            ret = self._value(b, "RETURN", "0", 0)
            body.append(f"    return {ret}")
        return [f"{info['lua']} = function({', '.join(info['params'])})", *body, "end"]

    # -- hat blocks --------------------------------------------------------------

    def _handler(self, b: dict) -> list[str]:
        self.count += 1
        t, f = b["type"], b.get("fields") or {}
        body = self._chain((b.get("inputs") or {}).get("DO"), 2, 0)
        if t == "rsmm_on_every":
            secs = f.get("SECONDS")
            if isinstance(secs, bool) or not isinstance(secs, int | float) or secs < MIN_SECONDS:
                raise EditorError(f"'every' needs seconds of {MIN_SECONDS} or more")
            self.uses.add("safe")
            return [f"R.schedule.every_main({_num(secs, 'every')}, function()",
                    "    if not R.entity.ready() then return end",
                    "    __safe(function()", *body, "    end)", "end)"]
        if t == "rsmm_on_event":
            ev = f.get("EVENT")
            if ev not in LIFECYCLE:
                raise EditorError(f"no event {ev!r}")
            name = ev
        else:
            ev = str(f.get("NAME") or "")
            if not _EVENT_RE.match(ev):
                raise EditorError(f"no game event {ev!r}")
            name = "gameplay:" + ev
        self.uses.add("run")
        return [f"R.on({_lstr(name)}, function()", "    __run(function()", *body,
                "    end)", "end)"]

    # -- statements --------------------------------------------------------------

    def _chain(self, link, indent: int, depth: int) -> list[str]:
        """The statements of a block and every block after it."""
        out: list[str] = []
        block = (link or {}).get("block") or (link or {}).get("shadow")
        while block:
            if depth > MAX_DEPTH:
                raise EditorError("the blocks are nested too deeply")
            if block.get("enabled") is not False:
                out += [("    " * indent) + ln for ln in self._stmt(block, depth)]
            nxt = block.get("next") or {}
            block = nxt.get("block")
        return out

    def _stmt(self, b: dict, depth: int) -> list[str]:
        self.count += 1
        t, f, inputs = b.get("type"), b.get("fields") or {}, b.get("inputs") or {}
        sub = lambda name: self._chain(inputs.get(name), 1, depth + 1)   # noqa: E731
        val = lambda name, default="0": self._value(b, name, default, depth)   # noqa: E731

        if t == "controls_if":
            es = b.get("extraState") or {}
            n = int(es.get("elseIfCount") or 0)
            if not 0 <= n <= 32:
                raise EditorError("too many 'else if' branches")
            out = [f"if {val('IF0', 'false')} then", *sub("DO0")]
            for i in range(1, n + 1):
                out += [f"elseif {val(f'IF{i}', 'false')} then", *sub(f"DO{i}")]
            if es.get("hasElse"):
                out += ["else", *sub("ELSE")]
            return [*out, "end"]
        if t == "controls_repeat_ext":
            frame = self._enter_loop()
            body = sub("DO")
            self.loops.pop()
            return [f"for _ = 1, math.min(math.floor({val('TIMES', '1')}), {MAX_REPEAT}) do",
                    *body, *self._continue_label(frame), "end"]
        if t == "controls_for":
            self.uses.add("range")
            var = self._var(f)
            head = f"{val('FROM', '1')}, {val('TO', '10')}, {val('BY', '1')}"
            frame = self._enter_loop()
            body = sub("DO")
            self.loops.pop()
            return ["do", f"    local __from, __to, __by = __range({head})",
                    f"    for {var} = __from, __to, __by do",
                    *["        " + ln for ln in body],
                    *["        " + ln for ln in self._continue_label(frame)], "    end", "end"]
        if t == "controls_forEach":
            self.uses.add("lists")
            var = self._var(f)
            frame = self._enter_loop()
            body = sub("DO")
            self.loops.pop()
            return [f"for _, {var} in ipairs(__list({val('LIST', '{}')})) do", *body,
                    *self._continue_label(frame), "end"]
        if t == "controls_whileUntil":
            cond = val("BOOL", "false")
            if f.get("MODE") == "UNTIL":
                cond = f"(not {cond})"
            elif f.get("MODE") != "WHILE":
                raise EditorError("unknown loop kind")
            frame = self._enter_loop()
            body = sub("DO")
            self.loops.pop()
            return ["do", "    local __turns = 0", f"    while {cond} do",
                    "        __turns = __turns + 1",
                    f"        if __turns > {MAX_WHILE} then break end",
                    *["    " + ln for ln in body],
                    *["    " + ln for ln in self._continue_label(frame)], "    end", "end"]
        if t == "controls_flow_statements":
            if not self.loops:
                raise EditorError("break and continue only work inside a loop")
            if f.get("FLOW") == "BREAK":
                return ["do break end"]
            frame = self.loops[-1]
            frame["used"] = True
            return [f"goto {frame['label']}"]
        if t == "rsmm_stop":
            return ["do return end"]
        if t == "text_append":
            var = self._var(f)
            return [f"{var} = tostring({var}) .. tostring({val('TEXT', _lstr(''))})"]
        if t == "lists_setIndex":
            self.uses.add("lists")
            mode, where = f.get("MODE"), f.get("WHERE")
            if mode not in ("SET", "INSERT") or where not in _WHERE:
                raise EditorError("unsupported list position")
            return [f"__list_set({val('LIST', '{}')}, {_lstr(where)}, {val('AT', '1')}, "
                    f"{val('TO')}, {'true' if mode == 'INSERT' else 'false'})"]
        if t == "lists_getIndex":      # the statement form: remove an element
            self.uses.add("lists")
            if f.get("MODE") != "REMOVE" or f.get("WHERE") not in _WHERE:
                raise EditorError("unsupported list position")
            return [f"__list_get({val('VALUE', '{}')}, {_lstr(f['WHERE'])}, "
                    f"{val('AT', '1')}, true)"]
        if t == "rsmm_give_random":
            n = f.get("COUNT", 1)
            if isinstance(n, bool) or not isinstance(n, int | float) or not 1 <= n <= MAX_COUNT:
                raise EditorError(f"give 1 to {MAX_COUNT} random items")
            self.uses.add("give")
            return [f"__give(nil, {int(n)})"]
        if t == "variables_set":
            return [f"{self._var(f)} = {val('VALUE')}"]
        if t == "math_change":
            return [f"{self._var(f)} = {self._var(f)} + {val('DELTA')}"]
        if t == "procedures_callnoreturn":
            return [self._call(b, depth) ]
        if t == "rsmm_log":
            return [f"R.log({_lstr('[blocks] ')} .. tostring({val('TEXT', _lstr(''))}))"]
        if t == "rsmm_wait":
            secs = f.get("SECONDS")
            if isinstance(secs, bool) or not isinstance(secs, int | float) or secs < MIN_SECONDS:
                raise EditorError(f"'wait' needs seconds of {MIN_SECONDS} or more")
            self.uses.add("safe")
            return [f"R.schedule.after_main({_num(secs, 'wait')}, function()",
                    "    __safe(function()", *["    " + ln for ln in sub("DO")],
                    "    end)", "end)"]
        if t == "rsmm_give_item":
            item, n = str(f.get("ITEM") or ""), f.get("COUNT", 1)
            if not _NAME_RE.match(item):
                raise EditorError(f"no item {item!r}")
            if isinstance(n, bool) or not isinstance(n, int | float) or not 1 <= n <= MAX_COUNT:
                raise EditorError(f"{item}: give 1 to {MAX_COUNT} copies")
            self.uses.add("give")
            return [f"__give({_lstr(item)}, {int(n)})"]
        if t == "rsmm_grant_talent":
            name, tier = str(f.get("TALENT") or ""), f.get("TIER", 0)
            if not _NAME_RE.match(name):
                raise EditorError(f"no talent {name!r}")
            if tier not in (0, 1, 2, 3, "0", "1", "2", "3"):
                raise EditorError(f"{name}: the rarity is 0 (Common) to 3 (Legendary)")
            self.uses.add("talent")
            return [f"__talent({_lstr(name)}, {int(tier)})"]
        if t == "rsmm_grant_xp":
            self.uses.add("xp")
            return [f"__xp({val('AMOUNT')})"]
        if t == "rsmm_stat_add":
            stat = str(f.get("STAT") or "")
            if not _NAME_RE.match(stat):
                raise EditorError(f"no stat {stat!r}")
            self.uses.add("stat")
            return [f"__stat({_lstr(stat)}, {val('AMOUNT')}, {val('SECONDS')})"]
        if t == "rsmm_hp":
            fn = _HP_ACTIONS.get(f.get("ACTION"))
            if not fn:
                raise EditorError("unknown health action")
            return [f"{fn}({val('AMOUNT')})"]
        if t == "rsmm_shards":
            fn = _SHARD_ACTIONS.get(f.get("ACTION"))
            if not fn:
                raise EditorError("unknown shard action")
            return [f"{fn}({val('AMOUNT')})"]
        raise EditorError(f"the block {t!r} is not one the editor can run")

    def _enter_loop(self) -> dict:
        self.labels += 1
        frame = {"label": f"__next_{self.labels}", "used": False}
        self.loops.append(frame)
        return frame

    @staticmethod
    def _continue_label(frame: dict) -> list[str]:
        return [f"::{frame['label']}::"] if frame["used"] else []

    # -- values ------------------------------------------------------------------

    def _value(self, b: dict, name: str, default: str, depth: int) -> str:
        link = (b.get("inputs") or {}).get(name) or {}
        inner = link.get("block") or link.get("shadow")
        if not inner:
            return default
        if depth > MAX_DEPTH:
            raise EditorError("the blocks are nested too deeply")
        return self._expr(inner, depth + 1)

    def _var(self, fields: dict) -> str:
        ref = fields.get("VAR")
        vid = ref.get("id") if isinstance(ref, dict) else ref
        if vid not in self.var_names:
            raise EditorError("a block uses a variable that does not exist")
        return self.var_names[vid]

    def _call(self, b: dict, depth: int) -> str:
        es = b.get("extraState") or {}
        name = str(es.get("name") or "")
        if name not in self.procs:
            raise EditorError(f"a block calls the function {name!r}, which nothing defines")
        info = self.procs[name]
        args = [self._value(b, f"ARG{i}", "0", depth) for i in range(len(info["params"]))]
        return f"{info['lua']}({', '.join(args)})"

    def _expr(self, b: dict, depth: int) -> str:
        self.count += 1
        t, f = b.get("type"), b.get("fields") or {}
        val = lambda name, default="0": self._value(b, name, default, depth)   # noqa: E731
        if t == "math_number":
            return _num(f.get("NUM", 0), "a number block")
        if t == "text":
            s = str(f.get("TEXT") or "")
            if len(s) > MAX_TEXT:
                raise EditorError(f"text is limited to {MAX_TEXT} characters")
            return _lstr(s)
        if t == "logic_boolean":
            return "true" if f.get("BOOL") == "TRUE" else "false"
        if t == "logic_negate":
            return f"(not {val('BOOL', 'false')})"
        if t == "logic_operation":
            op = {"AND": "and", "OR": "or"}.get(f.get("OP"))
            if not op:
                raise EditorError("unknown logic operator")
            return f"({val('A', 'false')} {op} {val('B', 'false')})"
        if t == "logic_compare":
            op = _COMPARE.get(f.get("OP"))
            if not op:
                raise EditorError("unknown comparison")
            return f"({val('A')} {op} {val('B')})"
        if t == "math_arithmetic":
            op = _ARITH.get(f.get("OP"))
            if not op:
                raise EditorError("unknown arithmetic operator")
            return f"({val('A')} {op} {val('B')})"
        if t == "math_random_int":
            return f"math.random(math.floor({val('FROM')}), math.floor({val('TO')}))"
        if t == "text_join":
            n = int((b.get("extraState") or {}).get("itemCount") or 0)
            if not 0 <= n <= 32:
                raise EditorError("too many items in a join")
            parts = [f"tostring({val(f'ADD{i}', _lstr(''))})" for i in range(n)]
            return "(" + (" .. ".join(parts) if parts else _lstr("")) + ")"
        if t == "variables_get":
            return self._var(f)
        if t == "procedures_callreturn":
            return self._call(b, depth)
        if t == "logic_ternary":
            return (f"(function() if {val('IF', 'false')} then return {val('THEN')} "
                    f"else return {val('ELSE')} end end)()")
        if t == "math_single":
            x = val("NUM")
            op = f.get("OP")
            if op == "ABS":
                return f"math.abs({x})"
            if op == "NEG":
                return f"(-{x})"
            if op == "ROOT":
                return f"math.sqrt(math.max(0, {x}))"
            raise EditorError("unsupported math function")
        if t == "math_round":
            x = val("NUM")
            fn = {"ROUND": f"math.floor({x} + 0.5)", "ROUNDUP": f"math.ceil({x})",
                  "ROUNDDOWN": f"math.floor({x})"}.get(f.get("OP"))
            if not fn:
                raise EditorError("unsupported rounding")
            return fn
        if t == "math_modulo":
            self.uses.add("math")
            return f"__mod({val('DIVIDEND')}, {val('DIVISOR', '1')})"
        if t == "math_constrain":
            return f"math.max({val('LOW')}, math.min({val('VALUE')}, {val('HIGH', '100')}))"
        if t == "math_number_property":
            prop = f.get("PROPERTY")
            if prop not in _NUMPROPS:
                raise EditorError("unsupported number property")
            self.uses.add("math")
            return (f"__numprop({val('NUMBER_TO_CHECK')}, {_lstr(prop)}, "
                    f"{val('DIVISOR', '1')})")
        if t == "math_random_float":
            return "math.random()"
        if t == "text_length":
            return f"#tostring({val('VALUE', _lstr(''))})"
        if t == "text_isEmpty":
            return f"(tostring({val('VALUE', _lstr(''))}) == \"\")"
        if t == "lists_create_with":
            n = int((b.get("extraState") or {}).get("itemCount") or 0)
            if not 0 <= n <= 64:
                raise EditorError("too many items in a list")
            return "{" + ", ".join(val(f"ADD{i}") for i in range(n)) + "}"
        if t == "lists_length":
            self.uses.add("lists")
            return f"#__list({val('VALUE', '{}')})"
        if t == "lists_isEmpty":
            self.uses.add("lists")
            return f"(#__list({val('VALUE', '{}')}) == 0)"
        if t == "lists_getIndex":
            self.uses.add("lists")
            mode, where = f.get("MODE"), f.get("WHERE")
            if mode not in ("GET", "GET_REMOVE") or where not in _WHERE:
                raise EditorError("unsupported list position")
            return (f"__list_get({val('VALUE', '{}')}, {_lstr(where)}, {val('AT', '1')}, "
                    f"{'true' if mode == 'GET_REMOVE' else 'false'})")
        if t == "rsmm_item_count":
            return "(R.give.owned_count() or 0)"
        if t == "rsmm_hp_value":
            read = _HP_READS.get(f.get("WHAT"))
            if not read:
                raise EditorError("unknown health reading")
            return f"({read} or 0)"
        if t == "rsmm_xp_level":
            return "(R.xp.level() or 0)"
        if t == "rsmm_shards_value":
            return "(R.shards.get() or 0)"
        if t == "rsmm_stat_value":
            stat = str(f.get("STAT") or "")
            if not _NAME_RE.match(stat):
                raise EditorError(f"no stat {stat!r}")
            return f"(R.stat.get({_lstr(stat)}) or 0)"
        if t == "rsmm_hero_is":
            hero = str(f.get("HERO") or "")
            if not _NAME_RE.match(hero):
                raise EditorError(f"no hero {hero!r}")
            return (f"(R.hero.entity and R.hero.entity() and "
                    f"R.hero.entity_is({_lstr('Hero_' + hero)}) or false)")
        raise EditorError(f"the block {t!r} is not one the editor can run")


_PRELUDE = {
    "safe": '''local function __safe(fn)
    local ok, err = pcall(fn)
    if not ok then R.log("[blocks] " .. tostring(err)) end
end''',
    "run": '''-- Runs on the game's main thread once the hero exists (a minute at most), because
-- most actions build engine objects and the hero is not there at "run starts".
local function __run(fn)
    R.schedule.next_main(function()
        if R.entity.ready() then __safe(fn) return end
        local tries, handle = 0, nil
        handle = R.schedule.every_main(1, function()
            tries = tries + 1
            if R.entity.ready() then
                R.schedule.cancel(handle)
                __safe(fn)
            elseif tries > 60 then
                R.schedule.cancel(handle)
            end
        end)
    end)
end''',
    "range": f'''-- A for loop runs {MAX_REPEAT} times at most; a step of 0 is a step of 1.
local function __range(from, to, step)
    from, to, step = tonumber(from) or 0, tonumber(to) or 0, tonumber(step) or 1
    if step == 0 then step = 1 end
    if (to - from) / step > {MAX_REPEAT - 1} then to = from + step * {MAX_REPEAT - 1} end
    return from, to, step
end''',
    "math": '''local function __mod(a, b)
    a, b = tonumber(a) or 0, tonumber(b) or 0
    if b == 0 then return 0 end
    return a % b
end
local function __numprop(n, prop, d)
    n = tonumber(n) or 0
    if prop == "EVEN" then return n % 2 == 0
    elseif prop == "ODD" then return n % 2 == 1
    elseif prop == "WHOLE" then return n % 1 == 0
    elseif prop == "POSITIVE" then return n > 0
    elseif prop == "NEGATIVE" then return n < 0
    elseif prop == "DIVISIBLE_BY" then d = tonumber(d) or 0; return d ~= 0 and n % d == 0
    elseif prop == "PRIME" then
        if n < 2 or n % 1 ~= 0 then return false end
        for i = 2, math.floor(math.sqrt(n)) do if n % i == 0 then return false end end
        return true
    end
    return false
end''',
    "lists": '''-- Lists are Lua tables (1-based); anything else reads as an empty list.
local function __list(x) return type(x) == "table" and x or {} end
local function __list_index(t, where, at)
    local n = #t
    if where == "FIRST" then return 1, n end
    if where == "LAST" then return n, n end
    if where == "RANDOM" then return (n > 0 and math.random(1, n) or nil), n end
    at = math.floor(tonumber(at) or 0)
    if where == "FROM_END" then return n - at + 1, n end
    return at, n
end
local function __list_get(t, where, at, remove)
    t = __list(t)
    local i, n = __list_index(t, where, at)
    if i == nil or i < 1 or i > n then return nil end
    if remove then return table.remove(t, i) end
    return t[i]
end
local function __list_set(t, where, at, value, insert)
    t = __list(t)
    local i, n = __list_index(t, where, at)
    if i == nil then return end
    if insert then
        if where == "LAST" then i = n + 1 end
        table.insert(t, math.max(1, math.min(i, n + 1)), value)
    elseif i >= 1 and i <= n then
        t[i] = value
    end
end''',
    "give": '''-- One grant per tick, each counted before it runs (a grant fires game events).
local __give_queue = {}
local function __give(id, n)      -- id nil = a random item
    __give_queue[#__give_queue + 1] = { id = id, n = n }
end
R.on("run:start", function() __give_queue = {} end)
R.on("run:end", function() __give_queue = {} end)
R.schedule.every_main(1, function()
    local it = __give_queue[1]
    if not it or not R.entity.ready() or not R.give.ready() or R.give.count() <= 0 then return end
    it.n = it.n - 1
    if it.n <= 0 then table.remove(__give_queue, 1) end
    local ok
    if it.id then ok = R.give.by_name(it.id) else ok = R.give.random() ~= nil end
    if not ok and __give_queue[1] == it then table.remove(__give_queue, 1) end
end)''',
    "talent": '''local function __talent(name, tier)
    if #R.talent.controllers() == 0 then
        R.log("[blocks] no talent controller yet; skipped " .. name)
        return
    end
    R.talent.grant(name, tier)
end''',
    "xp": '''R.xp.arm()    -- before the run builds the level
local function __xp(amount)
    R.stat.enable_writes()
    if not R.xp.grant(amount) then R.log("[blocks] XP grant was refused") end
end''',
    "stat": '''local function __stat(name, amount, seconds)
    R.stat.enable_writes()
    R.stat.modify(name, amount, seconds > 0 and seconds or nil)
end''',
}
_ORDER = ("safe", "run", "range", "math", "lists", "give", "talent", "xp", "stat")


def validate_state(raw) -> dict:
    """``raw`` as a workspace state, or an ``EditorError``."""
    if raw is None:
        return empty_state()
    if not isinstance(raw, dict):
        raise EditorError("the block program must be an object")
    ws = raw.get("blocks")
    if ws is None:
        return empty_state()
    if not isinstance(ws, dict) or not isinstance(ws.get("blocks", []), list):
        raise EditorError("the block program has no block list")
    variables = raw.get("variables") or []
    if not isinstance(variables, list):
        raise EditorError("the variable list is not a list")
    if len(json.dumps(raw, separators=(",", ":"))) > 400_000:
        raise EditorError("the block program is too large")
    return {"blocks": ws, "variables": variables}


def is_empty(state: dict) -> bool:
    return not (state.get("blocks") or {}).get("blocks")


def compile_blocks(raw) -> tuple[str, list[str]]:
    """The marked ``init.lua`` section for the workspace ``raw`` (empty text for
    an empty program) and the warnings the page should show."""
    state = validate_state(raw)
    if is_empty(state):
        return "", []
    c = _Compiler(state)
    body = c.compile()
    if not body:
        return "", c.warnings
    if "run" in c.uses:
        c.uses.add("safe")
    prelude = "\n\n".join(_PRELUDE[k] for k in _ORDER if k in c.uses)
    # Positions and ids only move blocks around the canvas; the state is kept as
    # the page saved it so opening the mod puts the workspace back exactly.
    cfg = json.dumps(state, separators=(",", ":"), ensure_ascii=True)
    indent = lambda text: "\n".join(("    " + ln) if ln else ln for ln in text.splitlines())  # noqa: E731
    lua = f"""{BEGIN}
-- Written by the rsmm editor (Scripts tab, Blocks), which rewrites this section
-- when you save; your own code outside the two marker lines is left alone.
{CONFIG}{cfg}
do
    local R = require "rsmm"

{indent(prelude) + chr(10) + chr(10) if prelude else ""}{indent(chr(10).join(body))}
end
{END}
"""
    return lua, c.warnings
