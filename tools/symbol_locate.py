"""Locate a symbol's function in the current build from the prose in its note.

The design point, learned the expensive way
------------------------------------------
The first version of this scored every function in the corpus and took the
winner. That is backwards, and it produced confident wrong answers:

  * `Netcode_DropPeer`'s note quotes "max reconnection time attempt". That
    string is logged by its CALLER. Global scoring handed DropPeer the caller's
    address.
  * Three different symbols were handed the level-load orchestrator, because
    that one 1234-line function contains every "Level load - *" stage string
    any of their notes quote.
  * Struct offsets are decisive between two neighbours (6/6 vs 1/6) and pure
    noise across 54k functions, where thousands of bodies touch `+0x10`.

So: CONSTRAIN first, then discriminate. A constraint is a cheap, high-precision
rule that yields a handful of candidates; discrimination only ever runs inside
that pool. When no constraint applies the pool is the whole corpus and the
result says so, because "I had nothing to go on" and "I checked everything and
this won" must not look alike.

Constraints, most decisive first
--------------------------------
``vftable``       note names a class + slot -> exactly one function. Identity.
``vftable_ctor``  note names a class -> functions that STORE that vftable.
``callgraph``     note names an already-located symbol -> callers/callees of it.
``call_site``     note quotes a string -> the functions CALLED next to that
                  string's use. This is the orchestrator case above, and it is
                  the constraint global scoring cannot express.
``string``        note quotes a string -> functions containing it.
``const``         note carries a class hash / UID -> functions containing it.

Every candidate is reported with the constraint that produced it, so a human
reviewing a shortlist knows how much to trust it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent

# A quoted literal shorter than this matches half the binary ("ot", "id", ...).
MIN_STRING_ANCHOR = 6
# Hex literals in this range are code/data VAs from the OLD build — useless as
# content anchors and actively misleading (they resolve to nothing today).
VA_LO, VA_HI = 0x140000000, 0x142000000
# Offsets are mined down to +0x8 because discrimination now runs INSIDE a
# constrained pool, where "which of these five walks +0x8/+0x10/+0x18" is a
# real question. Globally they were noise, and the previous 0x20 floor threw
# away the whole layout CustomFlagList_ContainsAll and Netcode_Channel_LookupById
# are documented by.
MIN_OFFSET = 0x8
# A function this large is a container (an orchestrator, a god-function). It
# will match anybody's strings, so when one wins a string constraint we also
# offer what it CALLS near that string.
CONTAINER_LINES = 400

_QUOTED = re.compile(rf"['\"]([^'\"\n]{{{MIN_STRING_ANCHOR},80}})['\"]")
# Notes name distinctive engine identifiers WITHOUT quoting them —
# "EP2PConnectionState log strings", "EnemyTribeDefInternal::SearchFilter".
# Measured: mining only quoted text left 11 of 28 test symbols with no
# constraint at all, several of which carry an obvious unquoted token.
_IDENT = re.compile(
    r"\b((?:[A-Z][a-z0-9]+){2,}(?:::[A-Za-z0-9_]+)?"
    r"|[A-Z]{2,}[A-Za-z0-9]*(?:::[A-Za-z0-9_]+)+)\b"
)
# Prose CamelCase that is not an engine identifier. Anchoring on these matches
# arbitrary code and buries the real candidates.
_IDENT_STOP = {
    "Ghidra", "Pattern", "Verified", "Confirmed", "SwissTable", "MinHook",
    "NOTE", "TODO", "DOWNGRADED", "STATUS", "RECOVER", "Semantics", "Sibling",
    "Windows", "Empty", "Reward", "Level", "Loader", "Runtime", "Engine",
    "Generic", "Returns", "Reads", "Writes", "Adds", "Scans", "Walks",
}
_HEX = re.compile(r"0x([0-9a-fA-F]{4,16})")
_OFFSET = re.compile(r"\+0x([0-9a-fA-F]{2,4})\b")
_CLASS = re.compile(r"\b((?:oC|oI|oe::)[A-Za-z0-9_:<>]{4,})")
_VFT_SLOT = re.compile(r"vftable\s*\+\s*0x([0-9a-fA-F]+)|vftable slot (\d+)")
_CALL = re.compile(r"FUN_(1[0-9a-f]{8})\(")


# --------------------------------------------------------------------------


@dataclass
class Anchors:
    strings: set[str] = field(default_factory=set)
    consts: set[int] = field(default_factory=set)
    offsets: set[int] = field(default_factory=set)
    classes: set[str] = field(default_factory=set)
    symbols: set[str] = field(default_factory=set)   # other symbols named
    vft: tuple[str, int] | None = None               # (class, slot)

    def any_constraint(self) -> bool:
        return bool(self.strings or self.consts or self.classes
                    or self.symbols or self.vft)


def mine_anchors(note: str, known_symbols: set[str], self_name: str = "") -> Anchors:
    """Pull machine-usable anchors out of a symbol's prose note."""
    # Drop the boilerplate downgrade tail. It is near-identical across ~40
    # symbols ("resolves mid-instruction", "Pattern stripped", ...) and every
    # quoted word inside it would become a shared, meaningless anchor.
    head = re.split(r"\[20\d\d-\d\d-\d\d[: ]", note or "")[0]

    a = Anchors()
    a.strings = {m.group(1).strip() for m in _QUOTED.finditer(head)}
    a.strings = {s for s in a.strings if len(s) >= MIN_STRING_ANCHOR}

    for m in _HEX.finditer(head):
        v = int(m.group(1), 16)
        if VA_LO <= v < VA_HI or v < 0x10000:
            continue          # old-build VA, or a struct offset
        # 64-bit constants are KEPT. Excluding them threw away some of the
        # best anchors in the map: Netcode_Channel_LookupById is documented by
        # its hash multiplier 0xde5fb9d2630458e9, which is far more distinctive
        # than any 32-bit value, and the note carries nothing else.
        a.consts.add(v)

    a.offsets = {int(m.group(1), 16) for m in _OFFSET.finditer(head)}
    a.offsets = {o for o in a.offsets if o >= MIN_OFFSET}
    a.classes = {m.group(1).rstrip(":") for m in _CLASS.finditer(head)}
    a.symbols = {n for n in known_symbols if n in head and n != self_name}

    # Unquoted engine identifiers become string anchors too. Filtered against
    # the symbol map and the class list so a name we already track by another
    # route does not also enter as a weak text match.
    for m in _IDENT.finditer(head):
        tok = m.group(1)
        if tok in _IDENT_STOP or tok in known_symbols or tok in a.classes:
            continue
        if len(tok) >= 8:
            a.strings.add(tok)

    m = _VFT_SLOT.search(head)
    if m and a.classes:
        slot = int(m.group(1), 16) // 8 if m.group(1) else int(m.group(2))
        # Pick the class token NEAREST the word "vftable", not the longest.
        # "longest" chose oCDtEntityCpnt3DBookTabControllerSettings for a note
        # about the 3DBookController, and resolved slot 28 of the wrong table.
        here = m.start()
        best, best_d = None, 10**9
        for cm in _CLASS.finditer(head):
            d = abs(cm.start() - here)
            if d < best_d:
                best, best_d = cm.group(1).rstrip(":"), d
        a.vft = (best or max(a.classes, key=len), slot)
    return a


# --------------------------------------------------------------------------


class Build:
    """The decompiled corpus for one game build, plus its RTTI vtables."""

    def __init__(self, corpus: Path, vftables: Path) -> None:
        self.code: dict[int, str] = {}
        self.calls: dict[int, set[int]] = {}
        self.callers: dict[int, set[int]] = {}
        for line in corpus.open():
            rec = json.loads(line)
            addr = int(rec["addr"], 16)
            body = rec.get("code") or ""
            self.code[addr] = body
            # Exclude the self-match: the decompile's own signature line
            # contains `FUN_<addr>(`, so without this every function looks
            # recursive and "shares a callee with" becomes meaningless.
            self.calls[addr] = {int(x, 16) for x in _CALL.findall(body)} - {addr}
        for a, cs in self.calls.items():
            for c in cs:
                self.callers.setdefault(c, set()).add(a)

        self.vft: dict[str, list[dict]] = {}
        if vftables.exists():
            for line in vftables.open():
                rec = json.loads(line)
                self.vft.setdefault(rec["sym"].replace("::vftable", ""), []).append(rec)

    def lines(self, addr: int) -> int:
        return self.code.get(addr, "").count("\n")


@dataclass
class Candidate:
    addr: int
    via: str                 # which constraint produced it
    offsets_hit: int = 0
    offsets_total: int = 0
    call_multiplicity: int = 0
    score: float = 0.0
    note: str = ""

    @property
    def offset_frac(self) -> float:
        return self.offsets_hit / self.offsets_total if self.offsets_total else 0.0


def offset_tokens(off: int) -> tuple[str, ...]:
    """How Ghidra may render a struct offset in decompiled text.

    Values below 0x10 come out as DECIMAL (`param_2 + 8`), not hex, so matching
    only `0x8` silently never fires. That cost CustomFlagList_ContainsAll its
    locator: the routine plainly reads `+ 8`, `+ 0x10` and `* 0x18`, but scored
    2/3 and lost to two unrelated functions.
    """
    if off < 0x10:
        return (f"+ {off}", f"0x{off:x}")
    return (f"0x{off:x}",)


def _has_offset(body: str, off: int) -> bool:
    return any(tok in body for tok in offset_tokens(off))


# --------------------------------------------------------------------------
# structured locators
#
# Mining prose plateaus. Measured on the 28 hand-confirmed relocations, the
# best text miner reaches rank-1 on 25% of them, and 8 have no usable anchor in
# their note at all — the note says things like "engine vector growth helper,
# new_cap is the 3rd arg", which identifies the routine to a human reading the
# decompile and to nothing else. Every attempt to squeeze more out of the text
# traded one recovered symbol for another.
#
# So the durable answer is to stop guessing at prose and record the anchor as
# DATA when the symbol is found, while the person who found it still knows what
# identified it. A `locator` on a symbol is precise, re-checkable, and — unlike
# a byte pattern — survives the game being rebuilt.
#
#   "locator": {
#     "vftable": {"class": "oCDtEnemyDefinition", "slot": 18},
#     "calls":   ["Registry_RegisterInstance", "ResourceRef_Resolve"],
#     "called_by": ["LevelLoad_Orchestrator"],
#     "strings": ["Generation complete !"],
#     "consts":  ["0xde5fb9d2630458e9"],
#     "offsets": ["0x2b8", "0x2c0", "0x2c8"]
#   }
#
# Any subset is valid. `resolve_locator` intersects whatever is present, so a
# single decisive key (vftable) is enough and several weak ones combine.


def resolve_locator(b: Build, loc: dict, located: dict[str, int],
                    self_addr: int | None = None) -> tuple[list[int], str]:
    """Resolve a structured locator to matching addresses. Returns (addrs, why)."""
    pools: list[set[int]] = []
    why: list[str] = []
    # Anchor symbols that appear in their own pool. A big orchestrator often
    # contains a self-call in the decompile, so "callees of X" included X, and
    # the offset tie-break then picked the container over the routine it calls.
    anchors = {located[n] for k in ("calls", "called_by")
               for n in (loc.get(k) or []) if n in located}

    vft = loc.get("vftable")
    if isinstance(vft, dict) and "class" in vft and "slot" in vft:
        cls, slot = vft["class"], int(vft["slot"])
        found = set()
        for name, recs in b.vft.items():
            if name != cls:
                continue
            for rec in recs:
                if slot < len(rec["slots"]):
                    found.add(int(rec["slots"][slot]["va"], 16))
        pools.append(found)
        why.append(f"{cls}::vftable[{slot}]")

    for key, direction in (("calls", "calls"), ("called_by", "called by")):
        names = loc.get(key) or []
        for n in names:
            va = located.get(n)
            if va is None:
                continue
            pool = (b.callers.get(va, set()) if key == "calls"
                    else b.calls.get(va, set()))
            pools.append({a for a in pool if a in b.code and a not in anchors})
            why.append(f"{direction} {n}")

    # Call MULTIPLICITY. "Calls X" is weak when X is a common helper — 146
    # functions call Netcode_Channel_Unsubscribe. "Calls X thirty-odd times"
    # is a shape almost nothing else has, and it is exactly how a routine that
    # tears down a fixed list of subscriptions is recognised.
    for name, least in (loc.get("calls_at_least") or {}).items():
        va = located.get(name)
        if va is None:
            continue
        tok = f"FUN_{va:x}("
        pools.append({a for a, body in b.code.items()
                      if body.count(tok) >= int(least)})
        why.append(f"calls {name} >={least}x")

    # Co-callees: routines invoked by the same functions that invoke X. Some
    # utilities are identified purely by the company they keep —
    # NamedEvent_Id_FromCrc is "the leaf every static-init event-name interner
    # calls right after Crc32_TableInit", and it shares its 1658 callers with
    # that symbol exactly.
    for n in loc.get("co_called_with") or []:
        va = located.get(n)
        if va is None:
            continue
        sibs: set[int] = set()
        for caller in b.callers.get(va, ()):
            sibs |= {c for c in b.calls.get(caller, ()) if c != va and c in b.code}
        pools.append(sibs)
        why.append(f"co-called with {n}")

    for s in loc.get("strings") or []:
        pools.append({a for a, body in b.code.items() if s in body})
        why.append(f"contains {s!r}")

    for c in loc.get("consts") or []:
        tok = c if isinstance(c, str) else f"0x{c:x}"
        tok = tok.lower()
        pools.append({a for a, body in b.code.items() if tok in body})
        why.append(f"embeds {tok}")

    offsets_pre = [int(str(o), 16) for o in (loc.get("offsets") or [])]
    if not pools and len(offsets_pre) >= 4:
        # A large, specific offset SET can seed on its own. Five offsets like
        # 0xd70/0xd78/0xd7c/0xd80/0xd88 describe one struct in one routine;
        # requiring all of them keeps this from behaving like the global
        # offset scoring that made the first version useless.
        pools.append({a for a, body in b.code.items()
                      if all(_has_offset(body, o) for o in offsets_pre)})
        why.append(f"all {len(offsets_pre)} offsets")

    if not pools and loc.get("callers_min") is None:
        return [], "locator has no resolvable key"

    hits = (set.intersection(*pools) if len(pools) > 1
            else (pools[0] if pools else set()))

    # Size bounds. Not a strong anchor on its own, but several routines are
    # identified as much by shape as content — NamedEvent_Id_FromCrc is "the
    # small thing 1658 static initialisers call", and nothing else about it is
    # distinctive.
    # Caller count is a strong, build-invariant shape property for the engine's
    # hot leaf utilities: only 10 functions in the whole 54k-function corpus
    # have 1000+ callers, so "is called from everywhere" nearly identifies one
    # on its own. Nothing else about PtrVector_Resize or Id_FromCrc is
    # distinctive — they carry no strings and no notable constants.
    cmin = loc.get("callers_min")
    if cmin is not None:
        if not hits:
            hits = {a for a in b.code if len(b.callers.get(a, ())) >= int(cmin)}
        else:
            hits = {a for a in hits if len(b.callers.get(a, ())) >= int(cmin)}
        why.append(f">={cmin} callers")

    lo, hi = loc.get("lines_min"), loc.get("lines_max")
    if lo is not None:
        hits = {a for a in hits if b.lines(a) >= int(lo)}
        why.append(f">={lo} lines")
    if hi is not None:
        hits = {a for a in hits if b.lines(a) <= int(hi)}
        why.append(f"<={hi} lines")

    offsets = [int(str(o), 16) for o in (loc.get("offsets") or [])]
    if offsets and len(hits) > 1:
        # Offsets never SELECT on their own — they only rank inside whatever
        # the other keys already narrowed to.
        best, top = [], -1.0
        for a in hits:
            body = b.code.get(a, "")
            n = sum(1 for o in offsets if _has_offset(body, o))
            if n > top:
                best, top = [a], n
            elif n == top:
                best.append(a)
        if top > 0:
            # Still tied? Prefer the SMALLER function. A container matches any
            # offset set by sheer surface area, and the routine being sought is
            # essentially never the 1200-line orchestrator that calls it.
            if len(best) > 1:
                least = min(b.lines(a) for a in best)
                best = [a for a in best if b.lines(a) == least]
            hits = set(best)
            why.append(f"{int(top)}/{len(offsets)} offsets")

    return sorted(hits), " AND ".join(why)


# --------------------------------------------------------------------------
# constraints


def _by_vftable(b: Build, a: Anchors) -> list[Candidate]:
    if not a.vft:
        return []
    cls, slot = a.vft
    # Exact class name first: `oCDtEntityCpnt3DBookTabController` also CONTAINS
    # `...BookController`, and taking the substring match resolved slot 28 of
    # the wrong table (to `_guard_check_icall`).
    ordered = sorted(b.vft.items(),
                     key=lambda kv: (kv[0] != cls, cls not in kv[0], len(kv[0])))
    for name, recs in ordered:
        if name != cls and cls not in name:
            continue
        for rec in recs:
            if slot >= len(rec["slots"]):
                continue
            s = rec["slots"][slot]
            # CFG thunks and pure-virtual stubs fill unused slots in every
            # table; they are never the routine being sought.
            if s["name"] in ("_guard_check_icall", "_purecall"):
                continue
            va = int(s["va"], 16)
            if va in b.code:
                return [Candidate(va, f"vftable {name}[{slot}]")]
    return []


def _by_vftable_ctor(b: Build, a: Anchors) -> list[Candidate]:
    """Functions that STORE a named class's vftable — i.e. its constructors.

    Ghidra renders the store as `*param_1 = oCDtEnemyDefinition::vftable`, so
    the class name appears verbatim in the body. This is how EnemyDefinition_ctor
    was found: the ctor chain ends by assigning the most-derived vftable.
    """
    out: list[Candidate] = []
    for cls in a.classes:
        needle = f"{cls}::vftable"
        for addr, body in b.code.items():
            if needle in body:
                out.append(Candidate(addr, f"stores {cls}::vftable"))
    return out


def _by_callgraph(b: Build, a: Anchors, located: dict[str, int]) -> list[Candidate]:
    """Callers and callees of already-located symbols the note names."""
    out: list[Candidate] = []
    for name in a.symbols:
        va = located.get(name)
        if va is None:
            continue
        for c in b.callers.get(va, ()):
            # How MANY times the candidate calls it. A note saying the routine
            # "calls X on each" describes a body with dozens of call sites, not
            # one — NamedEvent_HeroUnsubscribeAll calls Channel_Unsubscribe 34
            # times while its neighbours call it once, and flat scoring buried
            # it below them.
            n = b.code.get(c, "").count(f"FUN_{va:x}(")
            cand = Candidate(c, f"calls {name}")
            cand.call_multiplicity = n
            out.append(cand)
        for c in b.calls.get(va, ()):
            if c in b.code:
                out.append(Candidate(c, f"called by {name}"))
    return out


# How far after a log string the routine it announces may sit. Measured
# against the confirmed set: Netcode_DropPeer is called ~30 lines past the
# "max reconnection time attempt" string it is documented by, because the
# decompiler emits the whole log-record construction in between. A window of
# 12 missed it entirely.
CALL_SITE_WINDOW = 40


def _calls_near(b: Build, addr: int, needle: str,
                window: int = CALL_SITE_WINDOW) -> set[int]:
    """Addresses called within `window` lines of `needle` in `addr`'s body."""
    lines = b.code.get(addr, "").split("\n")
    hits: set[int] = set()
    for i, line in enumerate(lines):
        if needle not in line:
            continue
        for j in range(i, min(len(lines), i + window)):
            for m in _CALL.finditer(lines[j]):
                hits.add(int(m.group(1), 16))
    return hits


def _by_call_site(b: Build, a: Anchors) -> list[Candidate]:
    """THE constraint global scoring cannot express.

    A note quotes a log or stage string, but the string usually lives in the
    routine's CALLER — the boot orchestrator logs "InitialLoading - MagicalObject
    SpawnAllObjects" and then calls the routine that does it. So for every
    function containing the string, offer what it CALLS near that string.
    """
    out: list[Candidate] = []
    for s in a.strings:
        for addr, body in b.code.items():
            if s not in body:
                continue
            for callee in _calls_near(b, addr, s):
                if callee in b.code:
                    out.append(Candidate(callee, f"called next to {s!r}"))
    return out


def _by_string(b: Build, a: Anchors) -> list[Candidate]:
    out: list[Candidate] = []
    for s in a.strings:
        for addr, body in b.code.items():
            if s in body:
                out.append(Candidate(addr, f"contains {s!r}"))
    return out


def _by_container_callee(b: Build, a: Anchors) -> list[Candidate]:
    """Every callee of a CONTAINER that matches one of the note's strings.

    `_by_call_site` only offers what is called within a window of the string,
    which fails when the decompiler emits a long log-record construction in
    between: HeroDef_LoadSkinEntity is called ~55 lines past the stage string
    that documents it, and widening the window far enough to catch it makes it
    useless everywhere else. A 1200-line orchestrator has on the order of a
    hundred callees — small enough to be a pool, and the struct offsets in the
    note then pick the right one out of it.
    """
    out: list[Candidate] = []
    for s in a.strings:
        for addr, body in b.code.items():
            if s not in body or b.lines(addr) <= CONTAINER_LINES:
                continue
            for callee in b.calls.get(addr, ()):
                if callee in b.code and b.lines(callee) <= CONTAINER_LINES:
                    out.append(Candidate(callee, f"callee of the fn holding {s!r}"))
    return out


def _by_co_callee(b: Build, a: Anchors, located: dict[str, int]) -> list[Candidate]:
    """Siblings: functions called by the same function that calls a known symbol.

    Notes describe order of operations — "Level load drains the queue right
    after posting GENERATE_REWARDS via NamedEvent_Dispatch". The target is
    neither a caller nor a callee of Dispatch; it is called *alongside* it.
    EventQueue_Drain is exactly this and was unreachable by any other rule.
    """
    out: list[Candidate] = []
    for name in a.symbols:
        va = located.get(name)
        if va is None:
            continue
        callers = b.callers.get(va, set())
        if len(callers) > 60:      # a utility called everywhere has no siblings
            continue
        for caller in callers:
            for sib in b.calls.get(caller, ()):
                if sib != va and sib in b.code:
                    out.append(Candidate(sib, f"called alongside {name}"))
    return out


def _by_const(b: Build, a: Anchors) -> list[Candidate]:
    out: list[Candidate] = []
    for c in a.consts:
        tok = f"0x{c:x}"
        for addr, body in b.code.items():
            if tok in body:
                out.append(Candidate(addr, f"embeds {tok}"))
    return out


# --------------------------------------------------------------------------


# A constraint yielding more than this is not constraining anything; treat it
# as evidence to rank by, not as a pool to search.
MAX_POOL = 400


def locate(b: Build, note: str, known: dict[str, int], self_name: str = "",
           claimed: dict[int, str] | None = None,
           top: int = 5) -> tuple[list[Candidate], Anchors]:
    """Rank candidate addresses for the routine described by `note`.

    `known` maps symbol name -> current address for symbols already located;
    `claimed` maps address -> owner for addresses another symbol already holds.
    """
    claimed = claimed or {}
    a = mine_anchors(note, set(known), self_name)

    pools: list[list[Candidate]] = [
        _by_vftable(b, a),
        _by_callgraph(b, a, known),
        _by_call_site(b, a),
        _by_container_callee(b, a),
        _by_co_callee(b, a, known),
        _by_string(b, a),
        _by_vftable_ctor(b, a),
        _by_const(b, a),
    ]

    # A pool bigger than MAX_POOL is not constraining anything on its own — but
    # it is still a good FILTER. Crc32_TableInit has 1658 callers, useless as a
    # candidate list, yet "is one of those 1658" is exactly the fact that
    # separates NamedEvent_Id_FromCrc from everything else its constants match.
    # So oversized pools are set aside and used to boost, never to seed.
    seeds = [p for p in pools if p and len(p) <= MAX_POOL]
    filters = [{c.addr for c in p} for p in pools if p and len(p) > MAX_POOL]

    # If nothing small enough seeded a pool, fall back to the INTERSECTION of
    # the oversized ones — two independent broad constraints usually meet in a
    # handful of functions.
    if not seeds and len(filters) >= 2:
        inter = set.intersection(*filters)
        if inter and len(inter) <= MAX_POOL:
            seeds = [[Candidate(addr, "intersection of broad constraints")
                      for addr in inter]]

    # Merge, keeping every reason an address was proposed. An address reached
    # by two independent constraints is far stronger than one reached twice by
    # the same constraint, so reasons are deduplicated by text.
    merged: dict[int, Candidate] = {}
    for pool in seeds:
        for c in pool:
            if c.addr in claimed:
                continue
            cur = merged.get(c.addr)
            if cur is None:
                merged[c.addr] = c
            else:
                cur.call_multiplicity = max(cur.call_multiplicity,
                                            c.call_multiplicity)
                if c.via not in cur.via:
                    cur.via += f" + {c.via}"

    if not merged:
        return [], a

    # Discriminate INSIDE the pool. Offsets are decisive here and were noise
    # globally: the pool is already the right handful of functions, so "which
    # of these walks the struct the note describes" is exactly the question.
    for c in merged.values():
        body = b.code.get(c.addr, "")
        c.offsets_total = len(a.offsets)
        c.offsets_hit = sum(1 for o in a.offsets if _has_offset(body, o))
        reasons = c.via.count("+") + 1
        c.score = reasons * 2.0 + c.offset_frac * 4.0
        # Membership in a broad constraint is corroboration, not a candidate
        # source — worth as much as one extra reason.
        for f in filters:
            if c.addr in f:
                c.score += 2.0
                c.via += " + in broad set"
        # Repeated calls to a named symbol are a strong shape signal; damped so
        # a 34-call body outranks a 1-call one without swamping every other
        # constraint.
        if c.call_multiplicity > 1:
            c.score += min(c.call_multiplicity, 40) ** 0.5
        # A container matches everybody. Its callees are already candidates via
        # _by_call_site, so demote the container itself rather than dropping it.
        if b.lines(c.addr) > CONTAINER_LINES and "called next to" not in c.via:
            c.score -= 1.5
            c.note = f"large ({b.lines(c.addr)} lines) — may be the caller"

    ranked = sorted(merged.values(), key=lambda c: (-c.score, c.addr))
    return ranked[:top], a
