"""Talent (in-game "Skill") value content builder — SDK entry point.

``emit()`` turns one ``[[content]] kind="talent"`` declaration into a patched
copy of a vanilla hero **entity** file, written straight into the mod's
``assets/`` tree so the applier installs it as a plain asset override (no
re-cook, no registration — the hero entity already exists in ``asset_map``).

A talent's effect magnitude is an f32 (or int32 count) inside
``EntitySettings/Heroes/Hero_<hero>/*.entity.ot.EntitySettingsResource.gen``;
the writer is the shadowed-value-aware
:func:`rsmm.engine.talent_values.set_talent_value`. A hero has many entity
files, so each ``value_patches`` label is applied to whichever of the hero's
files actually contains it (or to ``file`` if given to disambiguate).

Fields:
    ``hero`` (str, required)   hero name, e.g. ``Juliet`` (matches the
                               ``EntitySettings/Heroes/Hero_<hero>`` dir).
    ``file`` (str, optional)   substring of the entity filename to restrict to,
                               when the same label exists in several files.
    ``value_patches``          list of ``[label, old, new]`` or
                               ``[label, old, new, clear_override]`` (or dicts
                               with ``label``/``old``/``new``/``clear_override``).
                               ``clear_override`` disables a shadowed node's
                               selector binding so the inline edit applies (it
                               unbinds the selector/curve — e.g. card-count
                               scaling becomes flat).
    ``rewires``                list of ``{trigger, action}`` (or ``{from, to}``,
                               plus optional ``all = true`` / ``count``,
                               ``exact = true`` and ``within = "<node>"``)
                               GUID rewires: repoint a component reference whose
                               label contains ``trigger`` at the node referenced
                               by ``action`` — e.g. fire a different State from
                               an existing trigger. Needs ``file`` to select one
                               entity file. See ``talent-logic-rewire`` RE note.
    ``union_patches``          list of ``{label, index, old, new}`` writes to
                               the ``index``-th ``oCEntityValueUnion`` inside a
                               container node — the per-rarity-tier numbers in a
                               value selector, which ``value_patches`` cannot
                               reach because a selector holds one union per tier
                               rather than a single picker/union pair. Index
                               over ALL unions in the node (tier entries
                               interleave an enabled-bool with the number), and
                               always give ``old`` so a shifted index fails
                               loudly. Needs ``file``.
    ``int_patches``            list of ``{label, end_index, old, new}`` int32
                               writes for selector / value-union tier entries
                               that ``value_patches`` (f32, first-END only)
                               cannot reach. ``end_index`` is the 0-based END
                               marker after ``label``. Needs ``file``.

This replaces hand-coded talent mods (the older flow shipped a manually
byte-edited entity copy). See ``docs/MOD_AUTHORING.md`` and the
``talent-value-editing`` RE note.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...engine import talent_values as TV
from ...engine.entity_edit import EntityEdit
from ...engine.paths import DATA_DIR
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

_log = logging.getLogger(__name__)

#: Where vanilla hero entity files live in-repo (one subdir per hero).
_HEROES_DIR = DATA_DIR / "uncooked" / "EntitySettings" / "Heroes"
_GEN_GLOB = "*.entity.ot.EntitySettingsResource.gen"
#: Decoded asset-path prefix (forward-slash) the patched override is written at.
_ASSET_PREFIX = "EntitySettings/Heroes"


def _resolve_hero_dir(hero: str) -> Path | None:
    """Return the ``Hero_<hero>`` dir for a hero name, case-insensitively."""
    if not _HEROES_DIR.is_dir():
        return None
    low = hero.lower()
    for d in _HEROES_DIR.glob("Hero_*"):
        if not d.is_dir():
            continue
        stem = d.name[len("Hero_"):]
        if stem.lower() == low or d.name.lower() == low:
            return d
    return None


def _coerce_value_patches(raw) -> list[tuple[str, float, float, bool]]:
    """Normalise ``value_patches`` into ``(label, old, new, clear_override)``.

    Mirrors :func:`rsmm.sdk.kinds.items._coerce_value_patches`."""
    out: list[tuple[str, float, float, bool]] = []
    for vp in (raw or []):
        clear = False
        if isinstance(vp, dict):
            label, old, new = vp.get("label"), vp.get("old"), vp.get("new")
            clear = bool(vp.get("clear_override", vp.get("clear", False)))
        else:
            label, old, new = vp[0], vp[1], vp[2]
            clear = len(vp) > 3 and bool(vp[3])
        if not label or old is None or new is None:
            raise ContentError(
                f"value_patches entry needs label/old/new, got {vp!r}")
        out.append((str(label), float(old), float(new), clear))
    return out


def _label_in(cooked: bytes, label: str) -> bool:
    return any(tv.label == label
               for tv in TV.list_talent_values(cooked, include_spawner=True))


def _apply_patch(cooked: bytes, label: str, old: float, new: float,
                 clear: bool) -> bytes:
    """Apply one value patch, clearing a shadowing override first if asked."""
    if clear and TV.is_label_overridden(cooked, label):
        cooked = TV.clear_value_override(cooked, label)
    return TV.set_talent_value(cooked, label, new, expect=old)


def _coerce_rewires(raw) -> list[tuple[str, str, dict]]:
    """Normalise ``rewires`` into ``(trigger, action, count)`` triples.

    Each entry repoints a component reference whose label contains ``trigger``
    (a/k/a ``from``) at the node whose reference label contains ``action``
    (``to``) — a GUID rewire, see :meth:`EntityEdit.rewire_ref`. ``count``
    limits how many matching references move (default 1); ``all = true`` moves
    every one, which is what a tier-gated selector needs since it carries one
    condition reference per rarity.

    ``exact = true`` matches whole labels, and ``within = "<node name>"``
    only repoints a reference inside that node. Use both whenever the label
    text also appears inside a LONGER label elsewhere — a controller's
    ``[State] ...Skill Secondary Quick Bombs`` is a substring of a
    ``[Modifier] ...Skill Secondary Quick Bombs CD Reduction Modifier`` that
    comes first in the file, and a plain substring rewire hits that instead."""
    out: list[tuple[str, str, dict]] = []
    for rw in (raw or []):
        count: int | None = 1
        opts: dict = {}
        if isinstance(rw, dict):
            frm = rw.get("trigger", rw.get("from"))
            to = rw.get("action", rw.get("to"))
            if rw.get("all"):
                count = None
            elif rw.get("count") is not None:
                count = int(rw["count"])
            if rw.get("exact"):
                opts["exact"] = True
            if rw.get("within"):
                opts["within"] = str(rw["within"])
                if rw.get("within_span") is not None:
                    opts["within_span"] = int(rw["within_span"])
        else:
            frm, to = rw[0], rw[1]
            if len(rw) > 2:
                count = None if rw[2] in (None, "all") else int(rw[2])
        if not frm or not to:
            raise ContentError(
                f"rewires entry needs trigger/action (from/to), got {rw!r}")
        opts["count"] = count
        out.append((str(frm), str(to), opts))
    return out


def _coerce_int_patches(raw) -> list[tuple[str, int, int, int]]:
    """Normalise ``int_patches`` into ``(label, end_index, old, new)``.

    Sets the int32 just before the ``end_index``-th END marker of the node
    named ``label`` — for selector / value-union tier entries that
    ``value_patches`` (f32, first-END-only) cannot reach. See
    :meth:`EntityEdit.set_int_before_nth_end`."""
    out: list[tuple[str, int, int, int]] = []
    for ip in (raw or []):
        if isinstance(ip, dict):
            label = ip.get("label")
            end_index = ip.get("end_index", ip.get("index"))
            old, new = ip.get("old"), ip.get("new")
        else:
            label, end_index, old, new = ip[0], ip[1], ip[2], ip[3]
        if not label or end_index is None or old is None or new is None:
            raise ContentError(
                f"int_patches entry needs label/end_index/old/new, got {ip!r}")
        out.append((str(label), int(end_index), int(old), int(new)))
    return out


def _coerce_union_patches(raw) -> list[tuple[str, int, float, float]]:
    """Normalise ``union_patches`` into ``(label, index, old, new)``.

    Targets the ``index``-th ``oCEntityValueUnion`` under ``label`` — see
    :func:`rsmm.engine.talent_values.set_union_value`."""
    out: list[tuple[str, int, float, float]] = []
    for up in (raw or []):
        if isinstance(up, dict):
            label = up.get("label")
            index = up.get("index")
            old, new = up.get("old"), up.get("new")
        else:
            label, index, old, new = up[0], up[1], up[2], up[3]
        if not label or index is None or old is None or new is None:
            raise ContentError(
                f"union_patches entry needs label/index/old/new, got {up!r}")
        out.append((str(label), int(index), float(old), float(new)))
    return out


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Materialize one talent def into the mod's ``assets/`` tree."""
    C.validate_id("talent", defn.id)
    hero = defn.fields.get("hero")
    if not hero or not isinstance(hero, str):
        raise SchemaNotMined(
            f"talent {defn.id}: needs a 'hero' name (e.g. Juliet) to locate "
            f"its entity files. See docs/MOD_AUTHORING.md.")

    hero_dir = _resolve_hero_dir(hero)
    if hero_dir is None:
        raise ContentError(
            f"talent {defn.id}: no vanilla hero dir for {hero!r} under "
            f"EntitySettings/Heroes (is data/uncooked present?)")

    file_filter = defn.fields.get("file")
    file_filter = str(file_filter).lower() if file_filter else None
    patches = _coerce_value_patches(defn.fields.get("value_patches"))
    rewires = _coerce_rewires(defn.fields.get("rewires"))
    int_patches = _coerce_int_patches(defn.fields.get("int_patches"))
    union_patches = _coerce_union_patches(defn.fields.get("union_patches"))
    if not patches and not rewires and not int_patches and not union_patches:
        raise ContentError(
            f"talent {defn.id}: no value_patches, union_patches, rewires or "
            f"int_patches given")

    # Candidate hero entity files (optionally narrowed by `file`).
    candidates = [p for p in sorted(hero_dir.glob(_GEN_GLOB))
                  if file_filter is None or file_filter in p.name.lower()]
    if not candidates:
        raise ContentError(
            f"talent {defn.id}: no entity files in {hero_dir.name}"
            + (f" matching {file_filter!r}" if file_filter else ""))

    # Group patches by the file that actually carries each label, applying them
    # to in-memory copies; only changed files are written.
    edited: dict[Path, bytes] = {}
    for label, old, new, clear in patches:
        targets = [p for p in candidates
                   if _label_in(edited.get(p) or p.read_bytes(), label)]
        if not targets:
            raise ContentError(
                f"talent {defn.id}: value label {label!r} not found in "
                f"{hero}'s entity files"
                + (f" matching {file_filter!r}" if file_filter else ""))
        for p in targets:
            cur = edited.get(p) or p.read_bytes()
            try:
                edited[p] = _apply_patch(cur, label, old, new, clear)
            except ValueError as e:
                raise ContentError(f"talent {mod_id}/{defn.id}: {e}") from e

    # union_patches address a container node's Nth union (per-tier selector
    # numbers). Length-preserving, so they need no EntityEdit — but like the
    # edits below they are pinned to one component graph, not broadcast.
    if union_patches:
        if len(candidates) != 1:
            raise ContentError(
                f"talent {defn.id}: union_patches need `file` to select exactly "
                f"one entity file (matched {len(candidates)}: "
                f"{[p.name for p in candidates]})")
        p = candidates[0]
        cur = edited.get(p) or p.read_bytes()
        try:
            for label, index, old, new in union_patches:
                cur = TV.set_union_value(cur, label, index, new, expect=old)
        except ValueError as e:
            raise ContentError(f"talent {mod_id}/{defn.id}: {e}") from e
        edited[p] = cur

    # Rewires + int_patches operate on the cooked concat (GUID/selector level),
    # not the talent-value table, so they go through one EntityEdit per file.
    # Restrict to a single file (the `file` filter must disambiguate) — these
    # edits are pinned to a specific component graph, not broadcast by label.
    if rewires or int_patches:
        if len(candidates) != 1:
            raise ContentError(
                f"talent {defn.id}: rewires/int_patches need `file` to select "
                f"exactly one entity file (matched {len(candidates)}: "
                f"{[p.name for p in candidates]})")
        p = candidates[0]
        ed = EntityEdit(edited.get(p) or p.read_bytes())
        try:
            for frm, to, opts in rewires:
                ed.rewire_ref(frm, to, **opts)
            for label, end_index, old, new in int_patches:
                ed.set_int_before_nth_end(label, end_index, new, expect=old)
            edited[p] = ed.emit()
        except ValueError as e:
            raise ContentError(f"talent {mod_id}/{defn.id}: {e}") from e

    written: list[Path] = []
    for p, blob in edited.items():
        decoded = f"{_ASSET_PREFIX}/{hero_dir.name}/{p.name}"
        dest = out_dir / Path(*decoded.split("/"))
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(blob)
        written.append(dest)
    _log.info("talent %s/%s: patched %d hero file(s) for %s",
              mod_id, defn.id, len(written), hero)
    return written
