"""Every record of a profile save (`Profile_*.ob`), decoded field by field.

`savefile` reads the container (header, CRC, class registry) and the record
boundaries. This module reads what is INSIDE the records, using layouts taken
from the engine's own per-class serializers (vtable slot 3 of each class, build
b9c3642884a8, corpus `docs/_re/out_new`). The stream's read methods map to
types: slot +0x68/+0x70 one byte, +0x78/+0x90/+0x98 four, +0xa0 an inline
object (open marker, class index, body, close marker), +0xa8 an object id;
`FUN_140211680` is a 16-byte GUID. A serializer reads a field only above some
schema version, so each layout below is valid for exactly ONE class version:
`parse` refuses a save whose registry lists any other (a game patch that bumps
a class must not be read with the old layout).

What a record holds, by class (offsets are the in-memory members):

* every `*ProfileData`: GUID (which definition it is for) + u32.
* `oCGameLockPersistentData` (inline in skins, story, talents, achievements,
  heroes): `unlocked` (+0x10), `new` (+0x11), a list of object ids of the
  unlock conditions it waits on, and an inline event listener. The engine's
  own unlock (FUN_140696870) sets both bytes to 1; the game clears `new` once
  the player has seen the thing (so a real save is mostly 1/0), and
  FUN_140696550 keeps `new` at 0 on re-evaluation once it is 0 — it is the
  "new" badge. A fresh lock is 0/0. Re-locking is not sticky: the game
  re-evaluates a lock's conditions and opens it again if they are met.
* `oCDtHeroProfileData` v18: `level` (f32; the fraction is progress to the
  next level, clamped on load to the hero's maximum), then counters.
* `SkillProfileData` (a talent) v5: `tier` (i32, -1 none .. 3), then a lock.
* the unlock-condition classes serialize nothing: their records are empty and
  their state is computed from the rest.
* the root `oCDtGameProfile`, the LAST record (object ids index the records
  before it, in the object table's order): the ids of its profile objects, then
  `oCDtPlayerProfileData` inline, then `oCDtCurrentRunProfileData` (a
  suspended run) inline. The run is NOT decoded; it is kept byte for byte.

Fields are edited in place: every editable field is fixed-size, so no record
changes size and nothing else in the file moves. Re-sign before writing.
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass, field

from rsmm.engine import savefile as SF

#: (type, name). Types: guid, u8, u32, i32, f32, refs (u32 count + ids),
#: obj (inline object, parsed by its own class).
SCHEMAS: dict[str, tuple[int, list[tuple[str, str]]]] = {
    # class: (schema version the layout is for, fields)
    "oCDtMagicalObjectProfileData": (5, [("guid", "guid"), ("u32", "word"), ("u8", "f60"),
                                         ("u8", "f61"), ("u8", "f62"), ("i32", "f64"),
                                         ("u8", "f68")]),
    "oCDtHeroProfileData": (18, [("guid", "guid"), ("u32", "word"), ("f32", "level"),
                                 ("u32", "count30"), ("u32", "count32"), ("u32", "count36"),
                                 ("i32", "rank38"), ("u8", "flag108"), ("u32", "count34"),
                                 ("u32", "value3c"), ("i32", "enum40"), ("obj", "lock")]),
    "SkillProfileData": (5, [("guid", "guid"), ("u32", "word"), ("i32", "tier"), ("obj", "lock")]),
    "SkinProfileData": (0, [("guid", "guid"), ("u32", "word"), ("obj", "lock")]),
    "StoryProfileData": (0, [("guid", "guid"), ("u32", "word"), ("obj", "lock")]),
    "AchievementProfileData": (0, [("guid", "guid"), ("u32", "word"), ("obj", "lock")]),
    "MelodyProfileData": (0, [("guid", "guid"), ("u32", "word"), ("u8", "flag48"),
                              ("u8", "flag49"), ("i32", "value4c")]),
    "ChallengeProfileData": (0, [("guid", "guid"), ("u32", "word"), ("i32", "value30")]),
    "oCDtPlayerProfileData": (8, [("i32", "value08"), ("i32", "value0c"), ("i32", "value10"),
                                  ("u8", "flag14"), ("u32", "value18")]),
    "NamedEventGameLockConditionData": (0, [("u32", "word"), ("obj", "listener")]),
    "GameEventGameUnlockConditionData": (1, [("obj", "listener"), ("obj", "listener2")]),
    "oCGameLockPersistentData": (1, [("u8", "unlocked"), ("u8", "new"), ("refs", "conditions"),
                                     ("obj", "listener")]),
    "oCGameEventListener": (1, [("u32", "event"), ("f32", "value"), ("f32", "limit"),
                                ("i32", "key")]),
}
#: Classes whose serializer writes nothing (FUN_1400bb2f0 just returns 1).
EMPTY = frozenset({
    "HeroRankGameLockConditionData", "HeroProgressionUnlockConditionData",
    "HeroStoryUnlockConditionData", "AdditionalContentGameUnlockConditionData",
    "CompleteChallengeGameUnlockConditionData", "ObjectCollectionUnlockConditionData",
    "HeroSkillSuccessUnlockConditionData", "HeroOutfitUnlockConditionData",
})
ROOT = "oCDtGameProfile"
RUN = "oCDtCurrentRunProfileData"
#: Versions the root and the opaque run were read at.
FIXED = {ROOT: 12, RUN: 19}

_FMT = {"u8": "<B", "u32": "<I", "i32": "<i", "f32": "<f"}
_OPEN = struct.pack("<I", SF.MARKER_OPEN)
_CLOSE = struct.pack("<I", SF.MARKER_CLOSE)


@dataclass
class Field:
    type: str
    offset: int          # absolute, in save.data
    value: object


@dataclass
class Node:
    cls: str
    start: int
    end: int
    fields: dict[str, Field] = field(default_factory=dict)
    children: dict[str, Node] = field(default_factory=dict)

    def get(self, name: str):
        return self.fields[name].value


@dataclass
class Profile:
    save: SF.Save
    objects: list[Node]          # by object id: the object table's order
    player: Node
    run: Node                    # bounds only; never decoded
    root_refs: list[int]


def _check_versions(save: SF.Save) -> None:
    for c in save.classes:
        want = SCHEMAS[c.name][0] if c.name in SCHEMAS else FIXED.get(c.name)
        if c.name in EMPTY or want is None:
            continue
        if c.version != want:
            raise SF.SaveFormatError(f"{save.path}: {c.name} is schema v{c.version}; this "
                                     f"build of rsmm reads v{want}. A game update changed the "
                                     "save format; nothing is edited until rsmm is updated.")


def _obj(save: SF.Save, d: bytes, o: int) -> tuple[Node, int]:
    if d[o:o + 4] != _OPEN:
        raise SF.SaveFormatError(f"{save.path}: expected an object at 0x{o:x}")
    (ci,) = struct.unpack_from("<I", d, o + 4)
    if ci >= len(save.classes):
        raise SF.SaveFormatError(f"{save.path}: class index {ci} at 0x{o:x} is not registered")
    name = save.classes[ci].name
    node, p = Node(name, o, -1), o + 8
    if name in EMPTY:
        pass
    elif name in SCHEMAS:
        for t, f in SCHEMAS[name][1]:
            if t == "guid":
                node.fields[f] = Field(t, p, d[p:p + 16].hex())
                p += 16
            elif t == "refs":
                (n,) = struct.unpack_from("<I", d, p)
                if n > 100000:
                    raise SF.SaveFormatError(f"{save.path}: {n} references at 0x{p:x}")
                node.fields[f] = Field(t, p, list(struct.unpack_from(f"<{n}I", d, p + 4)))
                p += 4 + 4 * n
            elif t == "obj":
                node.children[f], p = _obj(save, d, p)
            else:
                node.fields[f] = Field(t, p, struct.unpack_from(_FMT[t], d, p)[0])
                p += struct.calcsize(_FMT[t])
    else:
        raise SF.SaveFormatError(f"{save.path}: no layout for {name}")
    if d[p:p + 4] != _CLOSE:
        raise SF.SaveFormatError(f"{save.path}: {name} at 0x{o:x} does not end where its "
                                 "layout says")
    node.end = p + 4
    return node, node.end


def parse(save: SF.Save) -> Profile:
    """Decode every record. Raises SaveFormatError unless every byte of every
    record is accounted for by its layout (each object ends exactly at its
    close marker), which is what makes an in-place edit safe."""
    _check_versions(save)
    d = bytes(save.data)
    table = SF.object_table(save)
    recs = SF.records(save)
    # The objects come first, in the table's order; the profile itself is last.
    if not recs or save.classes[recs[-1].cls].name != ROOT:
        raise SF.SaveFormatError(f"{save.path}: the last record is not the profile")
    if len(recs) != len(table) + 1 or any(
            r.cls != c for r, c in zip(recs[:-1], table, strict=True)):
        raise SF.SaveFormatError(f"{save.path}: records do not match the object table")
    objects = []
    for r in recs[:-1]:
        node, end = _obj(save, d, r.start)
        if end != r.end:
            raise SF.SaveFormatError(f"{save.path}: {node.cls} at 0x{r.start:x} overruns")
        objects.append(node)
    root = recs[-1]
    p = root.start + 8
    if p + 4 > root.end:
        raise SF.SaveFormatError(f"{save.path}: the profile is truncated")
    (n,) = struct.unpack_from("<I", d, p)
    if p + 4 + 4 * n > root.end:
        raise SF.SaveFormatError(f"{save.path}: the profile's object list overruns it")
    refs = list(struct.unpack_from(f"<{n}I", d, p + 4))
    p += 4 + 4 * n
    player, p = _obj(save, d, p)
    if player.cls != "oCDtPlayerProfileData":
        raise SF.SaveFormatError(f"{save.path}: no player data in the profile")
    (ci,) = struct.unpack_from("<I", d, p + 4)
    if d[p:p + 4] != _OPEN or save.classes[ci].name != RUN:
        raise SF.SaveFormatError(f"{save.path}: no run data in the profile")
    run = Node(RUN, p, root.end - 4)               # whatever is left, up to the root's close
    if any(i >= len(objects) for i in refs):
        raise SF.SaveFormatError(f"{save.path}: the profile names an object that is not there")
    return Profile(save, objects, player, run, refs)


# --- edits ---------------------------------------------------------------------------
#: Lock states the engine itself writes: FUN_140696870 (all conditions met)
#: sets +0x10/+0x11 = 0x0101 (unlocked, with its "new" badge); a lock no
#: condition has opened yet is 0x0000.
LOCK_STATES = {"unlocked": (1, 1), "locked": (0, 0)}
TIER_RANGE = (-1, 3)            # SkillProfileData +0xe0, as the loader converts old saves
LEVEL_RANGE = (0.0, 8.0)        # hero level; the loader clamps to the hero's own cap


def _put(save: SF.Save, f: Field, value) -> None:
    struct.pack_into(_FMT[f.type], save.data, f.offset, value)
    f.value = struct.unpack_from(_FMT[f.type], save.data, f.offset)[0]


def lock_state(lock: Node) -> str:
    """"unlocked" (seen or still marked new) or "locked"."""
    return "unlocked" if lock.get("unlocked") else "locked"


def set_lock(save: SF.Save, lock: Node, state: str) -> None:
    if lock.cls != "oCGameLockPersistentData":
        raise ValueError("not a lock")
    a, b = LOCK_STATES[state]
    _put(save, lock.fields["unlocked"], a)
    _put(save, lock.fields["new"], b)


def set_hero_level(save: SF.Save, hero: Node, level: float) -> None:
    lo, hi = LEVEL_RANGE
    if hero.cls != "oCDtHeroProfileData" or not lo <= float(level) <= hi:
        raise ValueError(f"a hero level is {lo:g} to {hi:g}")
    _put(save, hero.fields["level"], float(level))


def set_talent_tier(save: SF.Save, skill: Node, tier: int) -> None:
    lo, hi = TIER_RANGE
    if skill.cls != "SkillProfileData" or int(tier) != tier or not lo <= tier <= hi:
        raise ValueError(f"a talent tier is {lo} to {hi}")
    _put(save, skill.fields["tier"], int(tier))


# --- names -----------------------------------------------------------------------------
# A record's GUID sits in the definition it is for. Achievements, challenges and
# melodies each have a def file of their own; a hero's talents, skins and story
# pages are entries INSIDE its herodef, named by a key next to the GUID. Which
# side differs by kind, and was settled on the shipped herodefs by which reading
# leaves one entry per hero unnamed: a talent's "Skill Controller <talent>" and
# a memoir's "<Hero>_Memoir<N>_Title" come BEFORE its GUID, a skin's
# "<Hero>_<Skin>_Skin_Title" (or the shared "Book_Page_DefaultSkin_Title")
# AFTER it. Shown names come from the text banks where a key has one.
_DEF_DIRS = {
    "AchievementProfileData": "Definitions/Achievements",
    "ChallengeProfileData": "Definitions/Challenges",
    "MelodyProfileData": "Definitions/Melodies",
    "oCDtMagicalObjectProfileData": "EntitySettings/Objects/Magical_Objects",
}
_HERO_DIR = "Definitions/Heroes"
_IN_HERO = {"oCDtHeroProfileData", "SkillProfileData", "SkinProfileData", "StoryProfileData"}
_KEY = {
    "SkillProfileData": re.compile(r"^Skill Controller (.+)$"),
    "SkinProfileData": re.compile(r"^(\w+)_Skin_Title$|^Book_Page_DefaultSkin_Title$"),
    # \d* because the game's own data spells one first memoir "Carmilla_Memoir_Title".
    "StoryProfileData": re.compile(r"^(\w+?)_Memoir(\d*)_Title$"),
}
#: Which side of the GUID to look first (the other is the fallback).
_SIDE = {"SkillProfileData": "before", "StoryProfileData": "before", "SkinProfileData": "after"}


def _lstrings(b: bytes, lo: int, hi: int) -> list[tuple[int, str]]:
    """Length-prefixed ASCII strings that END before ``hi``: (start, text)."""
    out = []
    for m in re.finditer(rb"[\x20-\x7e]{3,}", b[lo:hi]):
        start = lo + m.start()
        if start < 4:
            continue
        (n,) = struct.unpack_from("<I", b, start - 4)
        if 3 <= n <= len(m.group()):
            out.append((start, m.group()[:n].decode("ascii")))
    return out


def _bank(name: str, lang: str = "EN") -> dict[str, str]:
    """``key -> text`` of ``Text/<name>~GAM.xls``, from the install (empty when
    it can't be read: names then fall back to the key)."""
    from rsmm.engine import corpus
    from rsmm.engine import text_patches as TP
    copies = corpus.install_copies(f"Text/{name}~GAM.xls.LocalText.gen")
    if not copies:
        return {}
    try:
        keys = TP.parse_text_file(copies[0]).entries
        vals = TP.parse_text_file(TP.lang_path_for(copies[0], lang)).entries
    except (OSError, ValueError):
        return {}
    return dict(zip(keys, vals, strict=False))


def _pretty(stem: str) -> str:
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", stem.replace("_", " "))
    return re.sub(r"\s+", " ", s).strip()


def name_index(guids: dict[str, str]) -> dict[str, dict[str, str]]:
    """``guid hex -> {"name", "group"}`` for the records it can name.
    ``guids`` maps each record's GUID to its class."""
    from rsmm.engine import corpus
    want = {bytes.fromhex(g): c for g, c in guids.items()}
    out: dict[str, dict[str, str]] = {}
    for cls, folder in _DEF_DIRS.items():
        mine = [g for g, c in want.items() if c == cls]
        if not mine:
            continue
        for rel in corpus.rels(folder, ".gen"):
            raw = corpus.read(rel)
            if not raw:
                continue
            stem = rel.rsplit("/", 1)[-1].split(".", 1)[0]
            for g in mine:
                if g in raw:
                    out[g.hex()] = {"name": _pretty(stem), "id": stem,
                                    "group": rel.rsplit("/", 2)[-2] if "Magical" in folder else ""}
    # Herodefs: a base file and its _UpdateN override can both hold an entry;
    # the override is what the game loads, so it is read last and wins.
    heroes = sorted(corpus.rels(_HERO_DIR, ".herodef.ot.DtHeroDefinition.gen"),
                    key=lambda r: ("_Update" in r, r))
    banks: dict[str, dict[str, str]] = {}
    for rel in heroes:
        raw = corpus.read(rel)
        if not raw:
            continue
        hero_id = re.sub(r"_Update\d+$", "", rel.rsplit("/", 1)[-1].split(".", 1)[0])
        hero = _pretty(hero_id)
        for g, cls in want.items():
            if cls not in _IN_HERO:
                continue
            at = raw.find(g)
            if at < 0:
                continue
            if cls == "oCDtHeroProfileData":
                out[g.hex()] = {"name": hero, "id": hero_id, "group": hero}
                continue
            before = (m for _s, text in reversed(_lstrings(raw, max(0, at - 6000), at))
                      if (m := _KEY[cls].match(text)))
            after = (m for _s, text in _lstrings(raw, at + 16, min(len(raw), at + 6000))
                     if (m := _KEY[cls].match(text)))
            first, second = (before, after) if _SIDE[cls] == "before" else (after, before)
            key = next(first, None) or next(second, None)
            if key is None:
                out[g.hex()] = {"name": "?", "id": "", "group": hero}
                continue
            if cls == "SkillProfileData":
                name = key.group(1)
            elif key.group(0) == "Book_Page_DefaultSkin_Title":
                common = banks.setdefault("Common", _bank("Common"))
                name = common.get(key.group(0)) or "Default outfit"
            else:
                kind = "Skins" if cls == "SkinProfileData" else "Memoirs"
                bank = banks.setdefault(kind + hero_id, _bank(f"Hero_{hero_id}_{kind}"))
                name = bank.get(key.group(0)) or (
                    _pretty(key.group(1).removeprefix(hero_id + "_")) if kind == "Skins"
                    else f"Memoir {key.group(2) or 1}")
            out[g.hex()] = {"name": name, "id": key.group(0), "group": hero}
    return out


def item_state(item: Node) -> str:
    """The `savefile.ITEM_STATES` name an item record is in, or "other"."""
    for name, want in SF.ITEM_STATES.items():
        if all(v is None or item.get(k) == v for k, v in want.items()):
            return name
    return "other"


def set_item_state(save: SF.Save, item: Node, state: str) -> None:
    if item.cls != "oCDtMagicalObjectProfileData":
        raise ValueError("not an item record")
    for k, v in SF.ITEM_STATES[state].items():
        if v is not None:
            _put(save, item.fields[k], v)
