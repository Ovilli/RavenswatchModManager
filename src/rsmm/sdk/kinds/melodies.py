"""**Melody** editor — retune the Piper's lost-melody definitions (SDK entry).

Like ``reward`` (and unlike the clone-under-a-new-id kinds), a ``melody`` def
is an **override of a retail** ``*.melodydef.ot``: the emitted asset lands at
the vanilla decoded path and ``rsmm apply`` backs up + replaces the original.

Why override-only, never clone
------------------------------
The retail corpus is exactly **12** melodydefs, and their decoded ``field_a``
values are the dense set ``{0..11}`` with no repeats — i.e. ``field_a`` is a
melody *enum index*, not free-form data. That is corroborated on the UI side:
``Ui\\Melodies`` ships exactly 12 per-melody icons (``UI_Melody_Icon_Galahad``
… ``UI_Melody_Icon_Turtle``) plus ``_bg``/``_Hover``/``_Locked`` chrome, and
the melodydef carries **no icon ref** — so the def→icon mapping is resolved by
index/name outside the asset. A 13th melodydef would therefore have no index
and no icon, the same wall documented for skins and heroes. This kind does not
try; it only edits the 12 that exist.

Fields:
    ``base`` (str, required)      retail melodydef stem to override, e.g.
                                  ``Fully_Heal`` (see
                                  ``data/uncooked/Definitions/Melodies``).
    ``effect`` (str, optional)    stem of another retail melody whose effect
                                  entity this melody should run instead —
                                  repoints ``entity_ref`` at
                                  ``Objects\\Melodies\\<effect>.entity.ot``.
                                  The melody keeps its own index, icon and
                                  name; only the granted effect changes.
    ``exclude`` (list[str], opt.) replaces the melody's game-modifier
                                  exclusion list — the run mutators under
                                  which this melody is withheld. Entries must
                                  be GameModifier definition stems
                                  (``NoBossTimer``, ``OneChapter``, …); an
                                  unknown name is a typo and raises. Pass
                                  ``[]`` to clear all exclusions.

Confidence: ``guess``. The codec round-trips all 12 retail defs byte-for-byte
and the field semantics come from a full-population mine (every exclusion
string in the corpus is an exact GameModifier stem), but **no in-game playtest
has confirmed that either lever changes behaviour**. See
``docs/_re/kinds/melodies.md``.
"""

from __future__ import annotations

import json
import logging
import struct
from pathlib import Path

from ...engine.cooked_schemas.definitions import _SPECS, DefinitionHandler
from ...engine.paths import DATA_DIR
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

_log = logging.getLogger(__name__)

_MELODY_DIR = DATA_DIR / "uncooked" / "Definitions" / "Melodies"
_MODIFIER_DIR = DATA_DIR / "uncooked" / "Definitions" / "GameModifiers"
_ASSET_SUBDIR = "Definitions/Melodies"
GEN_SUFFIX = ".melodydef.ot.lodyDefinition.gen"

#: Cooked-stream block framing (see ``rsmm.engine.ot_decoder``).
_BEGIN = bytes.fromhex("1111bbaa")
_END = bytes.fromhex("2222bbaa")
#: Block tag of the exclusion list. Every retail melodydef tail ends
#: ``… 1111bbaa <tag=5> <u32 count> <lstr>*N 2222bbaa 2222bbaa``.
_LIST_TAG = 5


def handler() -> DefinitionHandler:
    return DefinitionHandler(_SPECS["MelodyDefinition"])


def _entity_ref(stem: str) -> list[str]:
    return ["EntitySettings", f"Objects\\Melodies\\{stem}.entity.ot"]


def known_melodies() -> list[str]:
    if not _MELODY_DIR.is_dir():
        return []
    return sorted(p.name[: -len(GEN_SUFFIX)] for p in _MELODY_DIR.glob(f"*{GEN_SUFFIX}"))


def known_modifiers() -> list[str]:
    if not _MODIFIER_DIR.is_dir():
        return []
    return sorted({p.name.split(".", 1)[0] for p in _MODIFIER_DIR.iterdir() if p.is_file()})


def split_exclusions(tail: bytes) -> tuple[bytes, list[str], bytes]:
    """Split a decoded ``_tail_hex`` blob into
    ``(prefix, exclusion_names, suffix)``.

    Fails closed: anything that does not match the exact retail shape
    (trailing ``BEGIN(tag=5) <count> <lstr>*count END END`` running to
    end-of-tail) raises rather than guessing an offset.
    """
    o = tail.rfind(_BEGIN)
    if o < 0:
        raise ContentError("melodydef tail has no block framing")
    tag = struct.unpack_from("<I", tail, o + 4)[0]
    if tag != _LIST_TAG:
        raise ContentError(f"melodydef exclusion block has tag {tag}, expected {_LIST_TAG}")
    p = o + 8
    (count,) = struct.unpack_from("<I", tail, p)
    p += 4
    names: list[str] = []
    for _ in range(count):
        (n,) = struct.unpack_from("<I", tail, p)
        p += 4
        raw = tail[p : p + n]
        if len(raw) != n:
            raise ContentError("melodydef exclusion list truncated")
        names.append(raw.decode("ascii"))
        p += n
    if tail[p:] != _END + _END:
        raise ContentError("melodydef exclusion block does not close as expected")
    return tail[:o], names, tail[p:]


def join_exclusions(prefix: bytes, names: list[str], suffix: bytes) -> bytes:
    out = bytearray(prefix)
    out += _BEGIN + struct.pack("<II", _LIST_TAG, len(names))
    for name in names:
        raw = name.encode("ascii")
        out += struct.pack("<I", len(raw)) + raw
    out += suffix
    return bytes(out)


def _apply_exclude(doc: dict, names: list[str], defn_id: str) -> None:
    valid = known_modifiers()
    for name in names:
        if not isinstance(name, str) or not name:
            raise ContentError(f"melody {defn_id}: exclude entries must be non-empty strings")
        if valid and name not in valid:
            raise ContentError(
                f"melody {defn_id}: exclude {name!r} is not a GameModifier stem. "
                f"Known: {', '.join(valid)}."
            )
    prefix, _old, suffix = split_exclusions(bytes.fromhex(doc["_tail_hex"]))
    doc["_tail_hex"] = join_exclusions(prefix, names, suffix).hex()


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize an edited retail melodydef as an override asset."""
    C.validate_id("melody", defn.id)

    base = defn.fields.get("base")
    if not base or not isinstance(base, str):
        raise ContentError(
            f"melody {defn.id}: needs a 'base' (retail melodydef stem) to edit, "
            f'e.g. base="Fully_Heal". See docs/_re/kinds/melodies.md.'
        )

    base_gen = _MELODY_DIR / f"{base}{GEN_SUFFIX}"
    if not base_gen.is_file():
        raise SchemaNotMined(
            f"melody {defn.id}: base {base!r} not found under {_MELODY_DIR} — "
            f"pass a retail melodydef stem whose cooked def is present. "
            f"Known: {', '.join(known_melodies()) or '(corpus absent)'}."
        )

    effect = defn.fields.get("effect")
    exclude = defn.fields.get("exclude")
    if effect is None and exclude is None:
        raise ContentError(
            f"melody {defn.id}: no edits — give 'effect' (melody stem to borrow "
            f"the effect entity from) and/or 'exclude' (game-modifier stems)."
        )
    if effect is not None:
        if not isinstance(effect, str) or not effect:
            raise ContentError(f"melody {defn.id}: 'effect' must be a melody stem, got {effect!r}")
        if not (_MELODY_DIR / f"{effect}{GEN_SUFFIX}").is_file():
            raise ContentError(
                f"melody {defn.id}: effect {effect!r} is not a retail melody. "
                f"Known: {', '.join(known_melodies()) or '(corpus absent)'}."
            )
    if exclude is not None and not isinstance(exclude, (list, tuple)):
        raise ContentError(
            f"melody {defn.id}: 'exclude' must be a list of GameModifier stems, got {exclude!r}"
        )

    h = handler()
    doc = json.loads(h.decode_cooked(base_gen.read_bytes()))
    if effect is not None:
        doc["entity_ref"] = _entity_ref(effect)
    if exclude is not None:
        _apply_exclude(doc, list(exclude), defn.id)
    new_cooked = h.encode_container(json.dumps(doc).encode("utf-8"))

    # Override the RETAIL path — apply backs up + replaces the original.
    decoded_rel = f"{_ASSET_SUBDIR}/{base}{GEN_SUFFIX}"
    dest = out_dir / Path(*decoded_rel.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(new_cooked)
    _log.info("melody %s/%s: override %s (effect=%s, exclude=%s)",
              mod_id, defn.id, base, effect, exclude)
    return [dest]
