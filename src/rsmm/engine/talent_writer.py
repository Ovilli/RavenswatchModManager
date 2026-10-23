"""Write a talent's parts from field values instead of copying them.

The talent builder (``add_stat``, ``scale``, ``on_hit``) used to copy each part
out of another hero: Beowulf's self modifier, timer and restart event, Aladdin's
"state active -> number, else 0" selector, Romeo's Love Shield gate, Melusine's
owned flag, factor value and caster reader, Carmilla's multiply. A talent mod
then depended on six heroes' files staying as they were, and on each copied
part bringing nothing of its hero along. Every part is now written here
(``entity_parts``), with the layout and header values those copies had, so a
talent's edit reads only the files it edits. The parts are the ones proven in
game through the copies (``tests/test_talent_writer.py`` compares them).

Read off the shipped parts 2026-10-23:

* a rarity selector is one entry per tier, ``[controller's <tier> bool ->
  number]`` for Legendary, Epic and Rare, then ``[True -> Common number]``; the
  controller's tier accessors are ``talent_values.TIER_KEYS``;
* a "when" selector is ``[state active -> number], [True -> else]``;
* a self modifier targets an ``oCSelfEntityCollectorSettings`` (bool true);
* a gate test is a combiner of two ``oCEntityCpntSimpleBoolTestSettings``,
  each a bool picker reading a state (``0x0fd2832a`` on, ``0x0fd2833c`` off);
* a reader of the hero is a get-value over an owner collector, the hero's
  entity as template, and the value it reads.
"""

from __future__ import annotations

import struct

from . import entity_graph_edit as GE
from . import entity_parts as P
from . import talent_values as TV

_STATE = "oCEntityCpntStateSettings"
_VALUE = "oCEntityCpntValueSettings"
_SELECTOR = "oCEntityCpntValueSelectorSettings"
_ENTRY = "oCEntityCpntValueSelectorEntrySettings"
_MOD = "oCEntityCpntModifierSettings"
_TIMER = "oCEntityCpntTimerSettings"
_TESTER = "oCEntityCpntTesterSettings"
_GET = "oCEntityCpntGetValueSettings"
_OPS = "oCEntityCpntValueOperationsSettings"
_COLLECTORS = "oCEntityCollectorSelectorSettings"

#: Accessors a value picker reads another part through.
STATE_ON, STATE_OFF = 0x0FD2832A, 0x0FD2833C
READ_VALUE = 0x0FD2C964
#: The controller's tier bools, in the order shipped selectors test them.
_TIER_ORDER = ("Legendary", "Epic", "Rare")
_TIER_KEY = {name: key for key, name in TV.TIER_KEYS.items()}
_MULTIPLY = 0x17B29BE2
#: The unit modifier amounts are marked with (``entity_parts.Num.unit``).
_RATIO = 2
_NONE = P.Link()

#: The Timer class version whose Serialize writes the trailing picker.
_TIMER_TAIL_AT = (1, 9)


def link_to(ef: GE.EntityFile, name: str) -> P.Link:
    """A reference to the existing component ``name`` of ``ef``, as the game
    writes one (``EntityFile._picker``)."""
    return P._link(ef._picker(name), 0)[0]


class TalentWriter(P.PartWriter):
    """Writes parts into a hero's entity, all in one group (``Skill <T>``)."""

    def __init__(self, ef: GE.EntityFile, seed: str, group: str):
        super().__init__(ef, seed)
        self.group = group

    def _add(self, cls: str, name: str, values: dict, *, flags: int, mode: int = 1,
             group: str | None = None) -> P.Link:
        return self.add(cls, name, {"mode": mode, **values}, flags=flags,
                        group=self.group if group is None else group)

    def _read(self, source: P.Link, key: int, fallback: P.Num) -> P.Num:
        return P.Num(fallback.type, fallback.value, fallback.unit, source=source, key=key)

    def _bool(self, v: bool) -> P.Num:
        return P.Num(P.BOOL, bytes([int(v)]))

    def _entry(self, cond: P.Num, value: P.Num) -> bytes:
        return self.obj(_ENTRY, P.num_bytes(cond, self.ci) + P.num_bytes(value, self.ci))

    def _selector(self, name: str, entries: list[bytes]) -> P.Link:
        # Written as a body: the selector's own first field is also called
        # `mode`, so its field values cannot sit in one table with the prefix's.
        body = (struct.pack("<II", 0, len(entries)) + b"".join(entries)
                + b"\x00\x00" + P.num_bytes(self._bool(False), self.ci))
        return self.add(_SELECTOR, name, flags=0x101, group=self.group, body=body)

    # -- numbers --

    def rarity(self, name: str, controller: P.Link, amounts: dict[str, float]) -> P.Link:
        """A number per rarity of the card ``controller`` draws."""
        entries = [self._entry(self._read(controller, _TIER_KEY[t], self._bool(False)),
                               P.Num.f32(amounts[t])) for t in _TIER_ORDER]
        entries.append(self._entry(self._bool(True), P.Num.f32(amounts["Common"])))
        return self._selector(name, entries)

    def when(self, name: str, state: P.Link, then: P.Link, otherwise: float = 0.0) -> P.Link:
        """``then`` while ``state`` is active, else ``otherwise``."""
        return self._selector(name, [
            self._entry(self._read(state, STATE_ON, self._bool(False)),
                        self._read(then, READ_VALUE, P.Num.f32(0))),
            self._entry(self._bool(True), P.Num.f32(otherwise))])

    def value_of(self, name: str, source: P.Link, *, flag: bool = False) -> P.Link:
        """A Value holding ``source``: its number, or (``flag``) whether that
        state is active."""
        num = (self._read(source, STATE_ON, self._bool(False)) if flag
               else self._read(source, READ_VALUE, P.Num.f32(0)))
        return self._add(_VALUE, name, {"value": num, "flag": 0}, flags=0x101)

    def multiply(self, name: str, a: P.Link, a_key: int, b: P.Link, b_key: int, *,
                 group: str) -> P.Link:
        """``a`` x ``b``, as a value operation."""
        def operand(link: P.Link, key: int) -> bytes:
            return struct.pack("<Ii", 0, -1) + P.num_bytes(
                self._read(link, key, P.Num.f32(0)), self.ci)
        node = self.obj("oCEntityCpntNodeSettings", struct.pack("<II", _MULTIPLY, 2)
                        + operand(a, a_key) + operand(b, b_key))
        return self._add(_OPS, name, {"operations": node}, flags=0x101, group=group)

    # -- behaviour --

    def modifier(self, name: str, stat_key: int, amount: P.Link) -> P.Link:
        """A permanent modifier of the hero's own ``stat_key`` by ``amount``."""
        me = self.sub("oCSelfEntityCollectorSettings", P.num_bytes(self._bool(True), self.ci))
        return self._add(_MOD, name, {
            "modifier_id": stat_key, "duration": P.Num.f32(0),
            "amount": self._read(amount, READ_VALUE, P.Num.f32(0, _RATIO)),
            "targets": self.ids(_COLLECTORS, [me]), "value_4": P.Num.f32(1),
            "sources?": self.ids(_COLLECTORS, []), "id": P.Num.int(0), "flag": 1},
            flags=0x1, mode=0)

    def state(self, name: str, *, activates=(), deactivates=(), while_active=(),
              flags: int = 0x10001, mode: int = 1) -> P.Link:
        return self._add(_STATE, name, {
            "activates": list(activates), "deactivates?": list(deactivates), "list_2": [],
            "on_exit?": [], "disables_while_active?": [], "on_enter?": [],
            "while_active": list(while_active)}, flags=flags, mode=mode)

    def timer(self, name: str, seconds: float, ends: P.Link) -> P.Link:
        """A timer of ``seconds`` that switches ``ends`` off when it runs out."""
        c = self.ef.cf.classes[self.ci(_TIMER)]
        tail = {"ref_tail?": _NONE} if (c.version_major, c.version_minor) >= _TIMER_TAIL_AT \
            else {}
        return self._add(_TIMER, name, {
            "bias?": P.Num.f32(0), "count": P.Num.int(1), "on_tick": _NONE, "on_end": _NONE,
            "state": ends, "paused?": self._bool(False), "duration": P.Num.f32(seconds),
            "flag": 0, **tail}, flags=0x1)

    def gate(self, name: str, *, on: P.Link, off: P.Link, then: P.Link) -> P.Link:
        """Switch ``then`` on, only while ``on`` is active and ``off`` is not."""
        def test(state: P.Link, key: int) -> int:
            return self.sub("oCEntityCpntSimpleBoolTestSettings", P.num_bytes(
                self._read(state, key, self._bool(False)), self.ci) + struct.pack("<I", 0))
        tests = [test(on, STATE_ON), test(off, STATE_OFF)]
        combiner = self.obj("oCCombinerCpntTestSettings", b"\x00\x01"
                            + struct.pack(f"<I{len(tests)}I", len(tests), *tests))
        return self._add(_TESTER, name, {
            "on_true": then, "ref_2": _NONE, "on_false": _NONE, "ref_4": _NONE,
            "test": combiner, "ref_6": _NONE, "ref_7": _NONE}, flags=0x10001)

    def reader(self, name: str, owner_resource: str, value: P.Link) -> P.Link:
        """In an entity the hero spawns: ``value`` read from the hero
        (``owner_resource``, ``Heroes\\Hero_X\\Hero_X.entity.ot``)."""
        on = self.obj(P.VALUE_PICKER, b"\x00" + self.obj(
            P.UNION, struct.pack("<II", P.BOOL, 0) + b"\x01"))
        owner = self.sub("oCOwnerEntityCollectorSettings",
                         on + b"\x00" + self.obj("oCResourceWeakRef", bytes(8)) + b"\x00")
        template = self.obj("oCResourceWeakRef", P._lstr("EntitySettings")
                            + P._lstr(owner_resource))
        method = self.obj("EntityCpntMethodPicker", P.link_bytes(_NONE, self.ci) + b"\xff" * 4)
        return self._add(_GET, name, {"source": self.ids(_COLLECTORS, [owner]),
                                      "template": template, "value": value,
                                      "method": method}, flags=0x1, group="")
