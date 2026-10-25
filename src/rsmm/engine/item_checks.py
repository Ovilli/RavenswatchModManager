"""Traps in a built magical object that only show in a playtest.

Each one cost a playtest on Little Thumb Pebbles (an ``Increase_Shield`` copy
turned into "+30% crit for 5 s after a hit", 2026-10-20):

* the shield's modifier is granted for good (``duration -1``) on every hit,
  fine for a shield damage uses up, but as crit it stacked for the whole run;
* its amount was an operation that also multiplies by the hero's Level Healing,
  so 0.3 became ~3.0 (+300%) and grew with level;
* the card slot showing it was a plain number, so 0.3 printed "+0%".

Only modifiers the mod TOUCHED are checked (a stat swapped, or the part copied
in by a step): the shipped wiring of an untouched effect is what the game
intends. Warnings, not errors: each shape has a legitimate use.
"""

from __future__ import annotations

import re
import struct

from . import entity_fields as EF
from . import entity_graph as EG

_MODIFIER = "oCEntityCpntModifierSettings"
_STATE = "oCEntityCpntStateSettings"
_OPERATION = "oCEntityCpntValueOperationsSettings"
_SELECTOR = "oCEntityCpntValueSelectorSettings"
_GET_VALUE = "oCEntityCpntGetValueSettings"
_VALUE = "oCEntityCpntValueSettings"
_FORMAT = "oCEntityCpntStringFormatValueSettings"
_TARGET = re.compile(r"<- \[[^\]]+\] (?P<path>[^|]*?)\s*(?:'\"\"')?\s*$")


def _target(text: str) -> str | None:
    """The part name a field's reference text points at (``... <- [Kind] Scope\\Name``)."""
    m = _TARGET.search(text.split("|")[0])
    return m["path"].rsplit("\\", 1)[-1].strip() if m else None


def _fields(c: EG.Component) -> dict[str, EF.Field]:
    return {f.name: f for f in EF.fields(c)}


def item_warnings(ent: bytes, base: bytes, touched: set[str]) -> list[str]:
    """Warnings for the built item ``ent`` (``base`` = the shipped item it was
    copied from). ``touched``: modifier names whose stat the mod swapped."""
    g = EG.parse(ent, "")
    comps = {c.name: c for c in g.components}
    shipped = {c.name for c in EG.parse(base, "").components}
    mods = [c for c in g.components if c.cls == _MODIFIER
            and (c.name in touched or c.name not in shipped)]
    out: list[str] = []
    out += _unread_stats(mods, touched)
    feeds: dict[str, str] = {}                    # amount source -> modifier
    for m in mods:
        f = _fields(m)
        amount = f.get("amount")
        src = _target(amount.text) if amount else None
        if src:
            feeds[src] = m.name
        if f.get("duration") and f["duration"].text.strip() == "f32 -1":
            for s in g.components:
                if s.cls != _STATE:
                    continue
                acts = _fields(s).get("activates")
                if acts and any(_target(i.text) == m.name for i in acts.items):
                    out.append(
                        f"{m.name!r} is granted for good (duration -1) each time "
                        f"{s.name!r} runs, so it stacks for the rest of the run. That "
                        f"suits a shield, which damage uses up; for a stat, time it "
                        f"(see 'A timed bonus' in the modding guide).")
        op = comps.get(src or "")
        if op is not None and op.cls == _OPERATION:
            for r in op.refs:
                o = comps.get(r.path.rsplit("\\", 1)[-1])
                reads = _reads(o, comps) if o is not None else None
                # An effect's `per_level = true` writes its own Level Healing
                # Selector: growing with level is what the author asked for.
                if o is not None and o.name.startswith("Level Healing Selector ") \
                        and o.name not in shipped:
                    continue
                if reads:
                    out.append(
                        f"{m.name!r}'s amount comes from {op.name!r}, which also "
                        f"multiplies by {o.name!r} (the hero's {reads}): the bonus "
                        f"is not the number you set and changes during the run. "
                        f"Link '{m.name}.amount' to a plain value to drop it.")
    for c in g.components:
        if c.cls != _FORMAT:
            continue
        for f in EF.fields(c):
            if f.kind != "obj" or not f.text or "<-" not in f.text:
                continue
            body = c.body[f.offset:f.offset + f.size]
            # Display mode 1 shows x100 as a percentage; 0 and 2 (Increase_Shield's
            # amount slot) print the number as it is.
            if len(body) < 8 or body[-8] == 1:
                continue
            src = _target(f.text)
            v = comps.get(src or "")
            if v is None or v.cls != _VALUE or src not in feeds:
                continue
            lit = _fields(v).get("value")
            m = re.match(r"f32 (-?[\d.e-]+)", lit.text) if lit else None
            if m and 0 < abs(float(m[1])) < 1:
                out.append(
                    f"{c.name!r} shows {src!r} ({m[1]}, the amount of {feeds[src]!r}) "
                    f"as a plain number, so the card reads 0. If it is a fraction, "
                    f"add a step: percent = \"{c.name}.{f.name}\", value = true.")
    return out


def _unread_stats(mods: list[EG.Component], touched: set[str]) -> list[str]:
    """A swapped stat that no shipped item, talent or hero ever changes.

    Many catalog stats only do something because the hero's data listens for
    them: "Primary/Secondary charge to damage" work through Hero_Common's "MO
    Charge To Damage" group, and nothing listens for the Defensive or Ultimate
    ones, so an item raising those does nothing (2026-10-22, Svalinn). A stat
    no shipped modifier writes has nothing showing the game reads it."""
    if not any(m.name in touched for m in mods):
        return []
    from .item_modifier import modifier_survey, stat_name
    used = modifier_survey().used
    if not used:
        return []
    out = []
    for m in mods:
        k = _fields(m).get("modifier_id")
        if m.name not in touched or k is None:
            continue
        key = struct.unpack_from("<I", m.body, k.offset)[0]
        if not used.get(key):
            out.append(
                f"{m.name!r} now changes {stat_name(key) or hex(key)!r}, which no item, "
                f"talent or hero in the game ever changes, so the game may never read "
                f"it and the effect may do nothing. Pick a stat a shipped item uses "
                f"(`rsmm editor`'s stat picker lists those first).")
    return out


def _reads(c: EG.Component, comps: dict[str, EG.Component]) -> str | None:
    """What hero value ``c`` reads, when it is a Get Value or a selector over one."""
    if c.cls == _GET_VALUE:
        return next((r.path.rsplit("\\", 1)[-1] for r in c.refs), "value")
    if c.cls == _SELECTOR:
        for r in c.refs:
            t = comps.get(r.path.rsplit("\\", 1)[-1])
            if t is not None and t.cls == _GET_VALUE:
                return _reads(t, comps)
    return None


def donor_leftovers(ent: bytes, donors: set[str]) -> list[str]:
    """References in ``ent`` that still name a part of an entity steps copied
    from: the copies point back into the donor, which this item does not carry."""
    out = []
    for stem in sorted(donors):
        pat = re.compile(rb"\[[A-Za-z ]+\] " + re.escape(stem.encode()) + rb"\\[ -~]+?(?=\"\"|$)")
        out += sorted({m.group().decode() for m in pat.finditer(ent)})
    return out
