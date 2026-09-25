"""Custom hero cooking: a hero with its own name, look and gameplay entity.

How the game assembles a hero (docs/_re/kinds/heroes.md, "How a hero is
assembled from data"):

    versiondef hero vector -> <Hero>.herodef
    herodef                -> name/desc text keys, portraits, skin entities
    skin entity            -> AliasPicker GUID
    ApplicationSettings.ot -> alias table: GUID -> Heroes\\Hero_<X>\\Hero_<X>.entity.ot

A skin carries no parent list; the alias is its only link to the gameplay
entity. And the gameplay entity is not self-contained: its pets and
projectiles read their OWNER's values by template path and scope
(``EntitySettings|Heroes\\Hero_Piper\\Hero_Piper.entity.ot`` +
``[Value] Hero_Piper\\Ability Basic\\...``). So a hero with its own gameplay
entity is a clone of the whole ``Hero_<Base>*`` family in the base's entity
folder, renamed consistently (paths and scopes), with the skins pointed at a
new alias. New files stay in the base's folders because a new cooked path is
anchored off a shipped sibling (``apply_mods.synthesize_encoded``).
"""

from __future__ import annotations

import re
import struct
import uuid
from dataclasses import dataclass, field
from pathlib import Path

from . import cooked, corpus
from . import entity_strings as ES
from . import rsc_cache as RC

HERO_DIR = "Definitions/Heroes"
HERODEF_SUFFIX = ".herodef.ot.DtHeroDefinition.gen"
ENTITY_SUFFIX = ".entity.ot.EntitySettingsResource.gen"
APP_SETTINGS = "DarkTalesResources/ApplicationSettings.ot"
#: Decoded path a mod emits to install its version of the alias table.
APP_SETTINGS_DECODED = "_root/" + APP_SETTINGS

_ALIAS_RE = re.compile(
    r"Vector\[(?P<i>\d+)\]=(?P<cls>C\d+)(?P<nl>\r?\n)\{\r?\n"
    r"u\|m_u32Val1=(?P<a>\d+)\r?\nu\|m_u32Val2=(?P<b>\d+)\r?\n"
    r"u\|m_u32Val3=(?P<c>\d+)\r?\nu\|m_u32Val4=(?P<d>\d+)\r?\n"
    r"s\|m_sName=(?P<name>[^\r\n]*)\r?\ns\|m_sArchive=(?P<arch>[^\r\n]*)\r?\n"
    r"s\|m_sStream=(?P<stream>[^\r\n]*)\r?\n\}\r?\n")
_LEN_RE = re.compile(r"(// class oe::Vector<class AliasDesc>\r?\nu\|Vector\.Length=)(\d+)")


class HeroCookError(ValueError):
    pass


# --------------------------------------------------------------------------
# the alias table (plaintext ApplicationSettings.ot)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Alias:
    guid: bytes           # 16 bytes, as an AliasPicker stores them
    name: str
    stream: str           # Heroes\Hero_X\Hero_X.entity.ot (single backslashes)


def aliases(text: str) -> list[Alias]:
    return [Alias(struct.pack("<4I", *(int(m[k]) for k in "abcd")), m["name"],
                  m["stream"].replace("\\\\", "\\"))
            for m in _ALIAS_RE.finditer(text)]


def add_alias(text: str, alias: Alias) -> str:
    """``text`` with ``alias`` appended to the alias vector (idempotent by GUID)."""
    found = list(_ALIAS_RE.finditer(text))
    ln = _LEN_RE.search(text)
    if not found or ln is None:
        raise HeroCookError("ApplicationSettings.ot has no AliasDesc vector")
    if any(a.guid == alias.guid for a in aliases(text)):
        return text
    last, nl = found[-1], found[-1]["nl"]
    vals = struct.unpack("<4I", alias.guid)
    block = (f"Vector[{int(last['i']) + 1}]={last['cls']}{nl}{{{nl}"
             + "".join(f"u|m_u32Val{k}={v}{nl}"
                       for k, v in zip((1, 2, 3, 4), vals, strict=True))
             + f"s|m_sName={alias.name}{nl}s|m_sArchive=EntitySettings{nl}"
             f"s|m_sStream={alias.stream.replace(chr(92), chr(92) * 2)}{nl}}}{nl}")
    text = text[:last.end()] + block + text[last.end():]
    return _LEN_RE.sub(lambda m: m[1] + str(int(m[2]) + 1), text, count=1)


def merge_app_settings(texts: list[str]) -> str:
    """Several mods' ApplicationSettings.ot: every mod-added alias, on the
    version that carries the fewest aliases (the one whose other edits, e.g.
    an ``ot`` patch, are not built on a hero mod's copy of the file)."""
    sets = [aliases(t) for t in texts]
    common = set.intersection(*({a.guid for a in s} for s in sets))
    base = min(range(len(texts)), key=lambda i: len(sets[i]))
    out = texts[base]
    for s in sets:
        for a in s:
            if a.guid not in common:
                out = add_alias(out, a)
    return out


def pristine_app_settings(game_dir: Path) -> str | None:
    p = game_dir / APP_SETTINGS
    bak = p.parent / (p.name + ".rsmm.bak")
    src = bak if bak.exists() else p
    return src.read_text(encoding="utf-8", errors="surrogateescape") if src.exists() else None


def alias_guid(mod_id: str, hero_id: str) -> bytes:
    """Stable per (mod, hero): a rebuild must not mint a new alias each time."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"rsmm:hero-alias:{mod_id}:{hero_id}").bytes


# --------------------------------------------------------------------------
# the base hero
# --------------------------------------------------------------------------

@dataclass
class HeroBase:
    herodef: str                    # Piper
    folder: str                     # Hero_Piper  (EntitySettings/Heroes/<folder>/)
    stem: str                       # Hero_Piper  (gameplay entity file stem)
    alias: Alias
    default_skin: str               # Heroes\Hero_Piper\Hero_Piper_Default.entity.ot
    text_bank: str                  # Hero_Piper_Common~GAM.xls
    body_fbx: str | None = None     # Characters\Heroes\Piper\Piper_GEO.fbx
    body_mat: str | None = None     # Characters\Heroes\Piper\Textures\M_Piper.mat.ot
    family: list[str] = field(default_factory=list)   # entity refs to clone

    @property
    def art_dir(self) -> str:
        return self.body_fbx.rsplit("\\", 1)[0] if self.body_fbx else ""


def herodef_rel(name: str) -> str:
    return f"{HERO_DIR}/{name}{HERODEF_SUFFIX}"


def entity_rel(ref: str) -> str:
    return "EntitySettings/" + ref.replace("\\", "/") + ".EntitySettingsResource.gen"


def _strings(raw: bytes) -> list[str]:
    return [t for _s, _o, t in ES.list_strings(raw)]


def _alias_guid_of(raw: bytes) -> bytes | None:
    cf = cooked.parse(raw)
    names = [c.name for c in cf.classes]
    if "AliasPicker" not in names:
        return None
    ai = names.index("AliasPicker")
    return next((s.payload[4:20] for s in cf.sections
                 if len(s.payload) >= 20 and struct.unpack_from("<I", s.payload, 0)[0] == ai),
                None)


def resolve_base(herodef: str, app_text: str) -> HeroBase:
    raw = corpus.read(herodef_rel(herodef))
    if raw is None:
        raise HeroCookError(f"no shipped herodef {herodef!r}")
    ts = _strings(raw)
    default = next((t for t in ts if t.endswith("_Default.entity.ot")), None)
    bank = next((ts[i - 1] for i, t in enumerate(ts) if t == "Hero_Name" and i), None)
    if default is None or bank is None:
        raise HeroCookError(f"{herodef}: herodef names no Default skin or name key")
    sraw = corpus.read(entity_rel(default))
    guid = _alias_guid_of(sraw) if sraw else None
    alias = next((a for a in aliases(app_text) if a.guid == guid), None)
    if alias is None:
        raise HeroCookError(f"{herodef}: its Default skin's alias is not in "
                            f"ApplicationSettings.ot")
    parts = alias.stream.split("\\")
    folder, stem = parts[1], parts[2][:-len(".entity.ot")]
    fam = [r.rsplit("/", 1)[-1][:-len(ENTITY_SUFFIX)]
           for r in corpus.rels(f"EntitySettings/Heroes/{folder}/", ENTITY_SUFFIX)]
    base = HeroBase(herodef, folder, stem, alias, default, bank,
                    family=sorted(f"Heroes\\{folder}\\{s}.entity.ot" for s in fam
                                  if s == stem or s.startswith(stem + "_")))
    main = corpus.read(entity_rel(alias.stream))
    base.body_fbx = _graphic_mesh(main, "Character Mesh") if main else None
    dts = _strings(sraw)
    def mat_after(key) -> str | None:
        return next((m for i, t in enumerate(dts) if key(t)
                     for m in dts[i + 1:i + 6] if m.endswith(".mat.ot")), None)
    # Beowulf's key is spelled "Chatacter Mesh Beowulf" in the shipped data, so
    # fall back to the first mesh material the Default skin sets.
    base.body_mat = (mat_after(lambda t: t.endswith("\\Base\\Character Mesh Material Value"))
                     or mat_after(lambda t: t.startswith("[Value]") and " Mesh " in t
                                  and t.endswith(" Material Value")))
    return base


def _graphic_mesh(raw: bytes, label: str) -> str | None:
    """The .fbx the entity's ``label`` 3D graphic object draws."""
    cf = cooked.parse(raw)
    names = [c.name for c in cf.classes]
    by: dict[int, list[str]] = {}
    for s, _o, t in ES.list_strings(raw):
        by.setdefault(s, []).append(t)
    for i, sec in enumerate(cf.sections):
        if len(sec.payload) < 4:
            continue
        ci = struct.unpack_from("<I", sec.payload, 0)[0]
        if ci < len(names) and names[ci] == "oCEntityCpnt3dGraphicObjectSettings":
            ss = by.get(i, [])
            if next((x for x in ss if not x.startswith("[")), None) == label:
                return next((x for x in ss if x.lower().endswith(".fbx")), None)
    return None


# --------------------------------------------------------------------------
# renaming a family
# --------------------------------------------------------------------------

@dataclass
class Renamer:
    """Maps every reference to the base family onto the clone's names.

    Two spellings reach a family member: its path
    (``Heroes\\Hero_Piper\\Hero_Piper_Projectile.entity.ot``) and its scope,
    the entity name that opens a component reference
    (``[Value] Hero_Piper_Projectile\\...``). Only names that ARE family members
    are renamed, so ``Hero_Piper`` never eats the front of an unrelated
    ``Hero_Piper_Common~GAM.xls`` text bank.
    """
    base: HeroBase
    new_stem: str
    extra: dict[str, str] = field(default_factory=dict)   # whole-string swaps

    def __post_init__(self) -> None:
        stems = sorted((r.rsplit("\\", 1)[-1][:-len(".entity.ot")] for r in self.base.family),
                       key=len, reverse=True)
        self._stems = {s: self.new_stem + s[len(self.base.stem):] for s in stems}
        alt = "|".join(map(re.escape, stems))
        self._scope = re.compile(r"(\] )(" + alt + r")(?=\\)")
        self._path = re.compile(re.escape(f"Heroes\\{self.base.folder}\\")
                                + "(" + alt + r")(?=\.entity\.ot)")

    def entity_ref(self, old_ref: str) -> str:
        return self.string(old_ref)

    def string(self, s: str) -> str:
        if s in self.extra:
            return self.extra[s]
        out = self._path.sub(lambda m: f"Heroes\\{self.base.folder}\\{self._stems[m[1]]}", s)
        out = self._scope.sub(lambda m: m[1] + self._stems[m[2]], out)
        return self._stems.get(out, out)

    def cooked(self, raw: bytes, guid_from: bytes | None = None,
               guid_to: bytes | None = None) -> bytes:
        out, _n = ES.rewrite_strings(raw, self.string)
        if guid_from and guid_to:
            out = out.replace(guid_from, guid_to)
        return out

    def cache(self, raw: bytes, add: tuple[str, ...] = ()) -> bytes:
        lines = {self._cache_line(ln) for ln in RC.parse(raw)} | set(add)
        return RC.render(sorted(lines))

    def _cache_line(self, line: str) -> str:
        root, _, rest = line.partition("|")
        ref, _, cls = rest.partition("|")
        return f"{root}|{self.string(ref)}|{cls}"


# --------------------------------------------------------------------------
# a hero's numbers
# --------------------------------------------------------------------------

def list_values(files: dict[str, bytes]) -> dict[str, list[tuple[str, float, bool]]]:
    """``label -> [(file, value, is_int)]`` for every labelled value node the
    reader can resolve in ``files`` (cooldowns, durations, radii, pet counts,
    damage multipliers). A label can live in more than one family member."""
    from .talent_values import list_talent_values
    out: dict[str, list[tuple[str, float, bool]]] = {}
    for name, raw in files.items():
        for tv in list_talent_values(raw, include_spawner=True):
            out.setdefault(tv.label, []).append((name, tv.value, tv.is_int))
    return out


def set_values(files: dict[str, bytes], values: dict[str, float]) -> dict[str, bytes]:
    """``files`` with each labelled value set.

    A key is a label (``Ultimate Power 2 Cooldown Max``), set in every member
    that carries it, or ``<Member>/<Label>`` (``Hero_Piper_Projectile/Lifetime
    Duration``) for one member only, as ``list_values`` names them. The edit is
    in place (4 bytes for a number, 1 for a bool), so no framing moves. An
    unknown key raises: a typo would otherwise ship a hero that is silently the
    base.
    """
    from .talent_values import _pack_value, list_talent_values
    out = dict(files)
    hits = dict.fromkeys(values, 0)
    for name, raw in files.items():
        buf = bytearray(raw)
        for tv in list_talent_values(raw, include_spawner=True):
            for key in (tv.label, f"{name}/{tv.label}"):
                if key in values:
                    packed = _pack_value(tv.type_code, float(values[key]))
                    buf[tv.offset:tv.offset + len(packed)] = packed
                    hits[key] += 1
        out[name] = bytes(buf)
    missing = sorted(k for k, n in hits.items() if not n)
    if missing:
        raise HeroCookError(f"no value named {', '.join(map(repr, missing))} in the hero's "
                            f"entities (`rsmm export-character <Base> --list-values`)")
    return out


# --------------------------------------------------------------------------
# component identity
# --------------------------------------------------------------------------

def family_guid_map(base_files: list[bytes], seed: str) -> dict[bytes, bytes]:
    """Old -> new identity for every component GUID the base family owns.

    A clone that keeps its donor's component GUIDs is a second resource
    claiming the donor's identity: it registers and resolves, and the engine
    cannot build it (measured on POI props; on a hero it spawned a body-less,
    light-less shell with no health). And the family's members point at each
    other's components BY GUID (Piper's entity at 39 of its pets' and
    projectiles', each skin at 3 of the hero's, the herodef at 22), so the new
    identities have to be ONE mapping applied to every file, or those links
    break instead. No shipped entity outside the family references them.
    """
    from .prop_cook import _ENTITY_GUID_LEN, component_guids, derive_guid
    return {old: derive_guid(f"{seed}#{old.hex()}")
            for raw in base_files for old in component_guids(raw)
            if old != bytes(_ENTITY_GUID_LEN)}


def apply_guid_map(raw: bytes, mapping: dict[bytes, bytes]) -> bytes:
    """Substitute ``mapping`` inside every section payload (never the header)."""
    cf = cooked.parse(raw)
    for sec in cf.sections:
        pl = sec.payload
        for old, new in mapping.items():
            if old in pl:
                pl = pl.replace(old, new)
        sec.payload = pl
    return cooked.emit(cf)
