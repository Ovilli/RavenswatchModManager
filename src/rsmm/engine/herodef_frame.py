"""A hero's roster record (``oCDtHeroDefinition``), decoded and written field
by field: the herodef of a hero written from scratch, with no other hero's
record copied (roadmap "Hero from scratch", the registration half).

Layout (all 13 shipped herodefs re-encode byte for byte, ``tests``): an object
graph, ``sections[0]`` the object table (class per object), object ``k`` =
``sections[k + 1]``, the last section the root, which lists objects by id.

* talent row (``SkillProfileDataSettings``): the controller's name and GUID
  (a hero's own talent controller, or Hero_Common's for the 6 ultimate rows),
  a lock (empty, or a rank-lock object id), the row's own GUID (what the save
  records), 9 tail bytes (``...01 00 00 00`` on the ultimate rows);
* story page: title/desc/extra text, footer pictures, a lock, corner picture;
* skin: GUID, title, icon, skin entity, a lock, two description texts;
* rank lock / progression unlock: text, a herodef, a rank; DLC unlock: app id;
  event conditions carry listener blocks and are kept as bytes;
* the root: roster position (``sort``: 1000 per hero, Scarlet first),
  portrait, name, 4 book portraits, story-text entity, talent rows, related
  heroes, "new hero" picture, 5 flags, story pages, 5 codex pictures, the
  hero's profile GUID, skins, description, its own lock, locked text, memoir
  key pattern, partner hero (Romeo/Juliet), unlock message, an optional UI
  frame and the LowRes skin entity.
"""

from __future__ import annotations

import struct
import uuid
from dataclasses import dataclass, field

from . import cooked

_B, _E = cooked.MARK_BEGIN, cooked.MARK_END
_NS = uuid.UUID("5c1f3e0e-8a3b-4e1d-9a7e-6d2b1f0c4a11")

SKILL, STORY, SKIN = ("SkillProfileDataSettings", "StoryProfileDataSettings",
                      "SkinProfileDataSettings")
RANK, PROGRESSION, DLC = ("HeroRankGameLockConditionSettings",
                          "HeroProgressionUnlockConditionSettings",
                          "AdditionalContentGameUnlockConditionSettings")
_LOCK, _LISTENER, _FILTER, _FLAGS = ("oCGameLockSettings", "oCGameEventListenerSettings",
                                     "oCCustomFlagFilter", "oCCustomFlagList")
_SPAWNER, _PICKER = "oCEntityGameUiSpawner", "oCEntityCpntPicker"


class HerodefError(ValueError):
    pass


@dataclass
class Text:
    """A localized text: ``kind`` ("Text"), bank, cached row, key; all empty
    (row -1) for none."""
    kind: str = ""
    bank: str = ""
    row: int = 0xFFFFFFFF
    key: str = ""

    @classmethod
    def of(cls, bank: str, key: str, row: int = 0xFFFFFFFF) -> Text:
        return cls("Text", bank, row, key)


@dataclass
class Lock:
    """``oCGameLockSettings``: the condition objects (ids) that lock its owner;
    empty = always available."""
    ids: list[int] = field(default_factory=list)
    z: int = 0
    m1: int = 0xFFFFFFFF
    a: int = 0
    b: int = 0
    t1: int = 0
    t2: int = 1
    t3: int = 0
    z2: int = 0


# ---- reading ----------------------------------------------------------------

class _R:
    def __init__(self, b: bytes, names: list[str]):
        self.b, self.o, self.names = b, 0, names

    def u8(self) -> int:
        v = self.b[self.o]
        self.o += 1
        return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.b, self.o)[0]
        self.o += 4
        return v

    def raw(self, n: int) -> bytes:
        v = bytes(self.b[self.o:self.o + n])
        if len(v) != n:
            raise HerodefError(f"truncated at {self.o}")
        self.o += n
        return v

    def lstr(self) -> str:
        n = self.u32()
        return self.raw(n).decode("utf-8")

    def res(self) -> tuple[str, str]:
        return (self.lstr(), self.lstr())

    def text(self) -> Text:
        if self.u32() != 3:
            raise HerodefError(f"no text at {self.o - 4}")
        return Text(self.lstr(), self.lstr(), self.u32(), self.lstr())

    def ids(self) -> list[int]:
        return [self.u32() for _ in range(self.u32())]

    def begin(self, cls: str) -> None:
        if self.raw(4) != _B or self.names[self.u32()] != cls:
            raise HerodefError(f"no {cls} block at {self.o - 8}")

    def end(self) -> None:
        if self.raw(4) != _E:
            raise HerodefError(f"no block end at {self.o - 4}")

    def lock(self) -> Lock:
        self.begin(_LOCK)
        ids, z = self.ids(), self.u8()
        self.begin(_LISTENER)
        m1 = self.u32()
        self.begin(_FILTER)
        self.begin(_FLAGS)
        a = self.u32()
        self.end()
        self.begin(_FLAGS)
        b = self.u32()
        self.end()
        self.end()
        t1, t2, t3 = self.u32(), self.u32(), self.u8()
        self.end()
        z2 = self.u8()
        self.end()
        return Lock(ids, z, m1, a, b, t1, t2, t3, z2)


# ---- writing ----------------------------------------------------------------

class _W:
    def __init__(self, names: list[str]):
        self.out, self.names = bytearray(), names

    def u8(self, v: int) -> None:
        self.out.append(v)

    def u32(self, v: int) -> None:
        self.out += struct.pack("<I", v & 0xFFFFFFFF)

    def raw(self, v: bytes) -> None:
        self.out += v

    def lstr(self, s: str) -> None:
        b = s.encode("utf-8")
        self.u32(len(b))
        self.out += b

    def res(self, r: tuple[str, str]) -> None:
        self.lstr(r[0])
        self.lstr(r[1])

    def text(self, t: Text) -> None:
        self.u32(3)
        self.lstr(t.kind)
        self.lstr(t.bank)
        self.u32(t.row)
        self.lstr(t.key)

    def ids(self, ids: list[int]) -> None:
        self.u32(len(ids))
        for i in ids:
            self.u32(i)

    def begin(self, cls: str) -> None:
        self.out += _B
        self.u32(self.names.index(cls))

    def end(self) -> None:
        self.out += _E

    def lock(self, k: Lock) -> None:
        self.begin(_LOCK)
        self.ids(k.ids)
        self.u8(k.z)
        self.begin(_LISTENER)
        self.u32(k.m1)
        self.begin(_FILTER)
        self.begin(_FLAGS)
        self.u32(k.a)
        self.end()
        self.begin(_FLAGS)
        self.u32(k.b)
        self.end()
        self.end()
        self.u32(k.t1)
        self.u32(k.t2)
        self.u8(k.t3)
        self.end()
        self.u8(k.z2)
        self.end()


# Each object kind and the root as (field, type) in stream order; the reader
# and the writer walk the same table, so they cannot drift apart.
_LAYOUTS: dict[str, list[tuple[str, str]]] = {
    SKILL: [("cls", "u32"), ("z", "u8"), ("name", "lstr"), ("controller", "guid"),
            ("lock", "lock"), ("guid", "guid"), ("tail", "raw9")],
    STORY: [("cls", "u32"), ("title", "text"), ("desc", "text"), ("extra", "text"),
            ("footer", "res"), ("footer_selected", "res"), ("lock", "lock"),
            ("corner", "res"), ("guid", "guid"), ("tail", "raw6")],
    SKIN: [("cls", "u32"), ("guid", "guid"), ("pre", "raw5"), ("title", "text"),
           ("icon", "res"), ("entity", "res"), ("lock", "lock"), ("mid", "raw2"),
           ("desc", "text"), ("mid2", "raw1"), ("desc2", "text")],
    RANK: [("cls", "u32"), ("text", "text"), ("hero", "res"), ("rank", "u32")],
    PROGRESSION: [("cls", "u32"), ("text", "text"), ("hero", "res"), ("rank", "u32")],
    DLC: [("cls", "u32"), ("text", "text"), ("app", "u32")],
    "root": [("head", "raw6"), ("sort", "u32"), ("portrait", "res"), ("name", "text"),
             ("book_standard", "res"), ("book_active", "res"), ("book_locked", "res"),
             ("book_unavailable", "res"), ("story_entity", "res"), ("rows", "ids"),
             ("related", "reslist"), ("new_hero", "res"), ("flags5", "bytelist"),
             ("stories", "ids"), ("codex", "reslist"), ("guid", "guid"),
             ("flags_g", "raw5"), ("skins", "ids"), ("desc", "text"), ("lock", "lock"),
             ("locked_text", "text"), ("memoir", "lstr"), ("partner_flag", "u8"),
             ("partner", "res"), ("pad2", "raw2"), ("unlock_message", "text"),
             ("flags_t", "raw2"), ("ui_frame", "spawner"), ("lowres", "res")],
}


def _read(r: _R, layout) -> dict:
    d: dict = {}
    for name, kind in layout:
        if kind == "guid":
            d[name] = r.raw(16)
        elif kind.startswith("raw"):
            d[name] = r.raw(int(kind[3:]))
        elif kind == "reslist":
            d[name] = [r.res() for _ in range(r.u32())]
        elif kind == "bytelist":
            d[name] = r.raw(r.u32())
        elif kind == "spawner":
            r.begin(_SPAWNER)
            ent = r.res()
            r.begin(_PICKER)
            g, label = r.raw(16), r.lstr()
            r.end()
            r.end()
            d[name] = (ent, g, label)
        else:
            d[name] = getattr(r, kind)()
    return d


def _write(w: _W, layout, d: dict) -> None:
    for name, kind in layout:
        v = d[name]
        if kind == "guid" or kind.startswith("raw"):
            w.raw(v)
        elif kind == "reslist":
            w.u32(len(v))
            for x in v:
                w.res(x)
        elif kind == "bytelist":
            w.u32(len(v))
            w.raw(v)
        elif kind == "spawner":
            ent, g, label = v
            w.begin(_SPAWNER)
            w.res(ent)
            w.begin(_PICKER)
            w.raw(g)
            w.lstr(label)
            w.end()
            w.end()
        else:
            getattr(w, kind)(v)


@dataclass
class Herodef:
    cf: cooked.CookedFile                 # its header and class table
    objects: list[tuple[str, dict | bytes]]   # (class, fields | raw payload)
    root: dict

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.cf.classes]


def decode(raw: bytes) -> Herodef:
    cf = cooked.parse(raw)
    names = [c.name for c in cf.classes]
    table = cf.sections[0].payload
    n = struct.unpack_from("<I", table, 0)[0]
    objects: list[tuple[str, dict | bytes]] = []
    for k in range(n):
        cls = names[struct.unpack_from("<I", table, 4 + 4 * k)[0]]
        payload = cf.sections[k + 1].payload
        if cls in _LAYOUTS:
            r = _R(payload, names)
            d = _read(r, _LAYOUTS[cls])
            if r.o != len(payload):
                raise HerodefError(f"object {k} ({cls}): {len(payload) - r.o} bytes unread")
            objects.append((cls, d))
        else:
            objects.append((cls, bytes(payload)))
    r = _R(cf.sections[-1].payload, names)
    root = _read(r, _LAYOUTS["root"])
    if r.o != len(r.b):
        raise HerodefError(f"root: {len(r.b) - r.o} bytes unread")
    return Herodef(cf, objects, root)


def encode(h: Herodef) -> bytes:
    names = h.names
    table = struct.pack("<I", len(h.objects)) + b"".join(
        struct.pack("<I", names.index(cls)) for cls, _ in h.objects)
    sections = [cooked.Section(table)]
    for cls, d in h.objects:
        if isinstance(d, bytes):
            sections.append(cooked.Section(d))
        else:
            w = _W(names)
            _write(w, _LAYOUTS[cls], d)
            sections.append(cooked.Section(bytes(w.out)))
    w = _W(names)
    _write(w, _LAYOUTS["root"], h.root)
    sections.append(cooked.Section(bytes(w.out)))
    h.cf.sections = sections
    return cooked.emit(h.cf)


# ---- a herodef written from data ---------------------------------------------

#: The classes a written herodef uses, in the shipped table order (format
#: metadata: each class's engine id, version and parent, read from the game).
_CLASSES = ("oCDtHeroDefinition", "oCDtDefinition", "oIResource", "oISerializable", SKILL,
            STORY, SKIN, _LOCK, _LISTENER, _FILTER, _FLAGS, _SPAWNER, _PICKER)
#: Format constants every shipped herodef has (13/13), and the most common
#: value where heroes differ (flags whose meaning is not known yet).
_HEAD = bytes.fromhex("000000000101")
_FLAGS5, _FLAGS_G, _FLAGS_T = bytes(5), bytes.fromhex("0101000000"), bytes.fromhex("0100")
_ULTIMATE_TAIL = bytes.fromhex("000000000001000000")
_COMMON = "Common~GAM.xls"


@dataclass
class Talent:
    controller: str            # "Skill Controller Attack Chop"
    controller_guid: bytes     # the hero's controller (Hero_Common's for an ultimate row)
    ultimate: bool = False


@dataclass
class Page:
    title: Text
    desc: Text
    footer: tuple[str, str]
    footer_selected: tuple[str, str]
    corner: tuple[str, str]


@dataclass
class Skin:
    entity: str                # Heroes\...\Hero_X_Default.entity.ot
    icon: tuple[str, str]
    title: Text = field(default_factory=lambda: Text.of(_COMMON, "Book_Page_DefaultSkin_Title",
                                                        0x12A))
    desc: Text = field(default_factory=lambda: Text.of(_COMMON, "Book_Page_DefaultSkin_Desc",
                                                       0x12B))


@dataclass
class Record:
    """A hero's roster record, every value its own."""
    hid: str
    sort: int                  # roster position (shipped: 1000 per hero)
    name: Text
    desc: Text
    portrait: tuple[str, str]
    book: tuple[tuple[str, str], tuple[str, str], tuple[str, str], tuple[str, str]]
    new_hero: tuple[str, str]
    codex: list[tuple[str, str]]
    talents: list[Talent]
    pages: list[Page]
    skins: list[Skin]
    lowres: str
    locked_text: Text = field(default_factory=lambda: Text.of(
        _COMMON, "Book_Page_Hero_Locked_Condition"))
    unlock_message: Text = field(default_factory=lambda: Text.of(
        _COMMON, "Message_Hero_Unlocked_Title", 0xA5))
    story_entity: str = "GameUis\\All_Book_Pages\\Hero_Single_Story_Text.entity.ot"


def _guid(hid: str, what: str) -> bytes:
    return uuid.uuid5(_NS, f"{hid}:{what}").bytes


def build(rec: Record, class_source: bytes) -> bytes:
    """``rec`` as a cooked herodef. ``class_source`` is any shipped herodef,
    read only for its class table's format metadata (ids, versions)."""
    src = cooked.parse(class_source)
    by_name = {c.name: c for c in src.classes}
    missing = [n for n in _CLASSES if n not in by_name]
    if missing:
        raise HerodefError(f"class metadata missing: {missing}")
    cf = cooked.CookedFile(variant=src.variant, hdr_a=src.hdr_a, flags=src.flags,
                           extra=src.extra, type_tag=src.type_tag)
    cf.classes = [cooked.ClassDef(c.name, c.class_id, c.version_major, c.version_minor,
                                  c.parent_id) for c in (by_name[n] for n in _CLASSES)]
    names = list(_CLASSES)
    objects: list[tuple[str, dict | bytes]] = []
    for t in rec.talents:
        objects.append((SKILL, {
            "cls": names.index(SKILL), "z": 0, "name": t.controller,
            "controller": t.controller_guid, "lock": Lock(),
            "guid": _guid(rec.hid, f"row:{t.controller}"),
            "tail": _ULTIMATE_TAIL if t.ultimate else bytes(9)}))
    rows = list(range(len(objects)))
    for i, p in enumerate(rec.pages):
        objects.append((STORY, {
            "cls": names.index(STORY), "title": p.title, "desc": p.desc, "extra": Text(),
            "footer": p.footer, "footer_selected": p.footer_selected, "lock": Lock(),
            "corner": p.corner, "guid": _guid(rec.hid, f"page:{i}"), "tail": bytes(6)}))
    pages = list(range(len(rows), len(objects)))
    for i, k in enumerate(rec.skins):
        objects.append((SKIN, {
            "cls": names.index(SKIN), "guid": _guid(rec.hid, f"skin:{i}"), "pre": bytes(5),
            "title": k.title, "icon": k.icon, "entity": ("EntitySettings", k.entity),
            "lock": Lock(), "mid": bytes(2), "desc": k.desc, "mid2": bytes(1),
            "desc2": k.desc}))
    skins = list(range(len(rows) + len(pages), len(objects)))
    root = {
        "head": _HEAD, "sort": rec.sort, "portrait": rec.portrait, "name": rec.name,
        "book_standard": rec.book[0], "book_active": rec.book[1],
        "book_locked": rec.book[2], "book_unavailable": rec.book[3],
        "story_entity": ("EntitySettings", rec.story_entity), "rows": rows, "related": [],
        "new_hero": rec.new_hero, "flags5": _FLAGS5, "stories": pages, "codex": rec.codex,
        "guid": _guid(rec.hid, "profile"), "flags_g": _FLAGS_G, "skins": skins,
        "desc": rec.desc, "lock": Lock(), "locked_text": rec.locked_text,
        "memoir": f"{rec.hid}/{rec.hid}_Memoir{{}}_Desc", "partner_flag": 0,
        "partner": ("", ""), "pad2": bytes(2), "unlock_message": rec.unlock_message,
        "flags_t": _FLAGS_T, "ui_frame": (("", ""), bytes(16), ""),
        "lowres": ("EntitySettings", rec.lowres)}
    return encode(Herodef(cf, objects, root))


__all__ = ["DLC", "PROGRESSION", "RANK", "SKILL", "SKIN", "STORY", "Herodef",
           "HerodefError", "Lock", "Page", "Record", "Skin", "Talent", "Text", "build",
           "decode", "encode"]
