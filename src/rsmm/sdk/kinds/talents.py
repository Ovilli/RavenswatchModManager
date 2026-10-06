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
                               ``exact = true``, ``within = "<node>"`` and
                               ``subtest_of = "<tester node>"``, which limits
                               the move to the conditions that tester checks)
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
    ``clone_nodes``            list of ``{source, name, retarget}``: append a
                               copy of the component ``source`` named ``name``
                               (new identity, attached to the entity's component
                               vector). ``retarget`` is a list of ``{from, to}``
                               reference labels repointed inside the copy, and
                               ``rename`` a list of ``{from, to}`` whole strings
                               replaced in it (e.g. a counter's event name).
                               ``modifier_stat = {hero, node}`` makes a copied
                               modifier change the same stat as that hero's
                               modifier (e.g. Beowulf's TRAIT cooldown one).
                               Nothing uses the copy until a ``rewires`` entry
                               points an existing reference at it (``action`` =
                               the new name). Needs ``file``.
    ``stats``                  table of modifier name -> the stat it changes
                               instead (a ``data/stat_keys.json`` name or a
                               ``0x`` key), as the item kind's ``stats``. The
                               amount keeps its old unit. Needs ``file``.
    ``add_stats``              list of ``{talent, stat, values, percent}``: give
                               the talent a stat bonus it does not have, e.g.
                               ``{talent = "Trait Fire", stat = "CD reduce
                               trait", values = [0.10, 0.15, 0.20, 0.25]}``.
                               ``values`` is one number, four (Common, Rare,
                               Epic, Legendary) or a table by rarity, in the
                               stat's own unit (0.25 on a CD stat = -25%). The
                               card gains a ``{N}`` slot showing it (``percent``,
                               default true, shows it x100). ``during = "DEFENSE"``
                               (or ATTACK, POWER, SPECIAL, TRAIT, DASH) applies it
                               only while that ability is in use; ``after =
                               "DEFENSE", seconds = 3`` applies it for 3 s each
                               time that ability is used (restarting on every
                               use). No ``file`` needed; see
                               ``rsmm.engine.talent_add_stat``.
    ``rebuild``                list of talent names whose own effect is turned
                               OFF, keeping the card: the talent builder's blank
                               slot. The card's number slots are cleared too, so
                               ``add_stats`` numbers start at ``{0}``; give the
                               card new text with a ``skill`` block. Runs before
                               ``add_stats``.
    ``include``                list of ``{talent, from}``: owning ``talent``
                               also switches on ``from``'s effect (same hero),
                               e.g. ``{talent = "Trait Active", from =
                               "Secondary Quick Bombs"}`` gives Red's
                               Shapeshifter Short Wick's bomb that explodes on
                               landing. ``from``'s rarity numbers take their
                               Common value. Runs after ``rebuild``.
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
from dataclasses import dataclass
from pathlib import Path

from ...engine import corpus
from ...engine import entity_append as EA
from ...engine import talent_values as TV
from ...engine.entity_edit import EntityEdit
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C

_log = logging.getLogger(__name__)

#: Where vanilla hero entity files live in-repo (one subdir per hero).
_HEROES_DIR = "EntitySettings/Heroes"
_GEN_SUFFIX = ".entity.ot.EntitySettingsResource.gen"
#: Decoded asset-path prefix (forward-slash) the patched override is written at.
_ASSET_PREFIX = "EntitySettings/Heroes"


@dataclass(frozen=True)
class _HeroDir:
    """A shipped ``EntitySettings/Heroes/Hero_<hero>`` directory, read from the
    mirror or the install (`engine.corpus`)."""

    name: str

    def entity_files(self) -> list[corpus.CorpusFile]:
        return corpus.files(f"{_HEROES_DIR}/{self.name}", _GEN_SUFFIX)


def _resolve_hero_dir(hero: str) -> _HeroDir | None:
    """Return the ``Hero_<hero>`` dir for a hero name, case-insensitively."""
    low = hero.lower()
    for name in corpus.subdirs(_HEROES_DIR):
        if not name.startswith("Hero_"):
            continue
        if name[len("Hero_"):].lower() == low or name.lower() == low:
            return _HeroDir(name)
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


def _coerce_clone_nodes(raw) -> list[tuple[str, str, list, list, tuple[str, str] | None]]:
    """Normalise ``clone_nodes`` into ``(source, name, retarget, rename, stat)``:
    two lists of ``(from, to)`` pairs and an optional ``(hero, node)`` naming
    the modifier whose stat the copy should change."""
    out: list[tuple[str, str, list, list, tuple[str, str] | None]] = []
    for cn in (raw or []):
        if not isinstance(cn, dict) or not cn.get("source") or not cn.get("name"):
            raise ContentError(f"clone_nodes entry needs source/name, got {cn!r}")
        pairs = []
        for rt in cn.get("retarget") or []:
            if not isinstance(rt, dict) or not rt.get("from") or not rt.get("to"):
                raise ContentError(f"clone_nodes retarget needs from/to, got {rt!r}")
            pairs.append((str(rt["from"]), str(rt["to"])))
        renames = []
        for rn in cn.get("rename") or []:
            if not isinstance(rn, dict) or not rn.get("from") or not rn.get("to"):
                raise ContentError(f"clone_nodes rename needs from/to, got {rn!r}")
            renames.append((str(rn["from"]), str(rn["to"])))
        stat = cn.get("modifier_stat")
        if stat is not None:
            if not isinstance(stat, dict) or not stat.get("hero") or not stat.get("node"):
                raise ContentError(
                    f"clone_nodes modifier_stat needs hero/node, got {stat!r}")
            stat = (str(stat["hero"]), str(stat["node"]))
        out.append((str(cn["source"]), str(cn["name"]), pairs, renames, stat))
    return out


def _modifier_stat_from(hero: str, node: str) -> bytes:
    """The stat key of the modifier ``node`` in any of ``hero``'s entity files."""
    hero_dir = _resolve_hero_dir(hero)
    if hero_dir is None:
        raise ContentError(f"modifier_stat: no vanilla hero dir for {hero!r}")
    found = []
    for p in hero_dir.entity_files():
        blob = p.read_bytes()
        if node.encode("ascii") not in blob:
            continue
        try:
            found.append(EA.modifier_stat(blob, node))
        except EA.EntityAppendError:
            continue
    if len(set(found)) != 1:
        raise ContentError(
            f"modifier_stat: expected one modifier named {node!r} on {hero}, "
            f"found {len(found)}")
    return found[0]


def _label_in(cooked: bytes, label: str) -> bool:
    return any(tv.label == label
               for tv in TV.list_talent_values(cooked, include_spawner=True,
                                               extra_labels=(label,)))


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
            if rw.get("subtest_of"):
                opts["subtest_of"] = str(rw["subtest_of"])
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


def _coerce_add_stats(raw) -> list[dict]:
    """Normalise ``add_stats`` entries; the values are checked when applied."""
    if raw is None:
        return []
    if isinstance(raw, dict):
        raw = [raw]
    if not isinstance(raw, list):
        raise ContentError(f"add_stats must be a list of tables, got {raw!r}")
    out = []
    for e in raw:
        if not isinstance(e, dict) or not e.get("talent") or "stat" not in e or "values" not in e:
            raise ContentError(f"add_stats entry needs talent, stat and values, got {e!r}")
        during = e.get("during")
        if during is not None and not isinstance(during, str):
            raise ContentError(f"add_stats: during must be an ability name, got {during!r}")
        after = e.get("after")
        if after is not None and not isinstance(after, str):
            raise ContentError(f"add_stats: after must be an ability name, got {after!r}")
        out.append({"talent": str(e["talent"]), "stat": e["stat"], "values": e["values"],
                    "percent": bool(e.get("percent", True)), "during": during,
                    "after": after, "seconds": e.get("seconds")})
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
            f"EntitySettings/Heroes — is the game install readable?")

    file_filter = defn.fields.get("file")
    file_filter = str(file_filter).lower() if file_filter else None
    patches = _coerce_value_patches(defn.fields.get("value_patches"))
    rewires = _coerce_rewires(defn.fields.get("rewires"))
    int_patches = _coerce_int_patches(defn.fields.get("int_patches"))
    union_patches = _coerce_union_patches(defn.fields.get("union_patches"))
    clone_nodes = _coerce_clone_nodes(defn.fields.get("clone_nodes"))
    from .items import _coerce_stats
    stats = _coerce_stats(defn.id, defn.fields.get("stats"))
    add_stats = _coerce_add_stats(defn.fields.get("add_stats"))
    rebuild = defn.fields.get("rebuild") or []
    if isinstance(rebuild, str):
        rebuild = [rebuild]
    if not isinstance(rebuild, list) or not all(isinstance(t, str) and t for t in rebuild):
        raise ContentError(f"talent {defn.id}: rebuild must be a list of talent names")
    include = defn.fields.get("include") or []
    if isinstance(include, dict):
        include = [include]
    if not isinstance(include, list) or not all(
            isinstance(e, dict) and isinstance(e.get("talent"), str) and e["talent"]
            and isinstance(e.get("from"), str) and e["from"] for e in include):
        raise ContentError(f"talent {defn.id}: include must be a list of "
                           "{talent, from} talent names")
    if not (patches or rewires or int_patches or union_patches or clone_nodes or stats
            or add_stats or rebuild or include):
        raise ContentError(
            f"talent {defn.id}: no value_patches, union_patches, rewires, "
            f"clone_nodes, stats, add_stats, rebuild, include or int_patches given")

    # Candidate hero entity files (optionally narrowed by `file`).
    candidates = [p for p in hero_dir.entity_files()
                  if file_filter is None or file_filter in p.name.lower()]
    if not candidates:
        raise ContentError(
            f"talent {defn.id}: no entity files in {hero_dir.name}"
            + (f" matching {file_filter!r}" if file_filter else ""))

    # Group patches by the file that actually carries each label, applying them
    # to in-memory copies; only changed files are written.
    #
    # Another talent block in this mod may already have written the same entity
    # during this emit (the previous emit's files are removed before any block
    # runs). Start from that copy, or this block silently discards its edits.
    edited: dict[corpus.CorpusFile, bytes] = {}
    for p in candidates:
        earlier = out_dir / Path(*f"{_ASSET_PREFIX}/{hero_dir.name}/{p.name}".split("/"))
        if earlier.is_file():
            edited[p] = earlier.read_bytes()

    # add_stats find their own file (the one holding the talent's controller),
    # and like clones they grow the file, so they run before the length-
    # preserving edits.
    def _home(talent: str):
        ctl = f"Skill Controller {talent}".encode()
        homes = [p for p in candidates if ctl in (edited.get(p) or p.read_bytes())]
        if len(homes) != 1:
            raise ContentError(f"talent {defn.id}: {len(homes)} of {hero}'s entity files "
                               f"hold a talent named {talent!r}")
        return homes[0]

    if rebuild:
        from ...engine import talent_add_stat as TA
        for talent in rebuild:
            p = _home(talent)
            try:
                edited[p], cleared = TA.rebuild_talent(edited.get(p) or p.read_bytes(),
                                                       talent=talent, seed=f"{mod_id}:{defn.id}")
            except TA.AddStatError as e:
                raise ContentError(f"talent {mod_id}/{defn.id}: {e}") from e
            _log.info("talent %s/%s: %s rebuilt (its effect is off; %d card number(s) "
                      "cleared)", mod_id, defn.id, talent, cleared)

    for entry in include:
        from ...engine import talent_add_stat as TA
        p = _home(entry["talent"])
        if _home(entry["from"]) != p:
            raise ContentError(f"talent {defn.id}: {entry['talent']!r} and {entry['from']!r} "
                               "are in different entity files")
        try:
            edited[p] = TA.include_talent(edited.get(p) or p.read_bytes(),
                                          talent=entry["talent"], other=entry["from"])
        except TA.AddStatError as e:
            raise ContentError(f"talent {mod_id}/{defn.id}: {e}") from e
        _log.info("talent %s/%s: %s now also runs %s", mod_id, defn.id,
                  entry["talent"], entry["from"])

    if add_stats:
        from ...engine import talent_add_stat as TA
        donor_dir = _resolve_hero_dir(TA.DONOR_HERO)
        donor = next((p for p in (donor_dir.entity_files() if donor_dir else [])
                      if p.name == f"Hero_{TA.DONOR_HERO}{_GEN_SUFFIX}"), None)
        if donor is None:
            raise ContentError(f"talent {defn.id}: add_stats needs the game's "
                               f"{TA.DONOR_HERO} files to copy a modifier from")
        during_donor = None
        if any(e["during"] or e["after"] for e in add_stats):
            ddir = _resolve_hero_dir(TA.DONOR_DURING_HERO)
            during_donor = next((p for p in (ddir.entity_files() if ddir else [])
                                 if p.name == f"Hero_{TA.DONOR_DURING_HERO}{_GEN_SUFFIX}"), None)
            if during_donor is None:
                raise ContentError(f"talent {defn.id}: 'during'/'after' need the game's "
                                   f"{TA.DONOR_DURING_HERO} files to copy a selector from")
        for entry in add_stats:
            p = _home(entry["talent"])
            try:
                edited[p], added = TA.add_stat(
                    edited.get(p) or p.read_bytes(), donor.read_bytes(),
                    talent=entry["talent"], stat=entry["stat"], values=entry["values"],
                    percent=entry["percent"], seed=f"{mod_id}:{defn.id}",
                    during=entry["during"], after=entry["after"], seconds=entry["seconds"],
                    during_donor_raw=(during_donor.read_bytes()
                                      if entry["during"] or entry["after"] else None))
            except TA.AddStatError as e:
                raise ContentError(f"talent {mod_id}/{defn.id}: {e}") from e
            _log.info("talent %s/%s: %s gets %s; card slot {%s}", mod_id, defn.id,
                      entry["talent"], entry["stat"], added.slot)

    # Clones change the file's structure (a new record, a longer component
    # vector), so they go first: every later edit re-reads the grown file, and
    # a rewire below can then point an existing reference at the new node.
    if clone_nodes:
        if len(candidates) != 1:
            raise ContentError(
                f"talent {defn.id}: clone_nodes need `file` to select exactly "
                f"one entity file (matched {len(candidates)}: "
                f"{[p.name for p in candidates]})")
        p = candidates[0]
        cur = edited.get(p) or p.read_bytes()
        try:
            for source, name, retarget, rename, stat in clone_nodes:
                key = _modifier_stat_from(*stat) if stat else None
                cur = EA.clone_component(cur, source, name, retarget, rename, key)
        except EA.EntityAppendError as e:
            raise ContentError(f"talent {mod_id}/{defn.id}: {e}") from e
        edited[p] = cur
    # Which stat a modifier changes: 4 bytes inside the modifier, so any order
    # works; it is pinned to one file because modifier names repeat across them.
    if stats:
        if len(candidates) != 1:
            raise ContentError(
                f"talent {defn.id}: stats need `file` to select exactly one "
                f"entity file (matched {len(candidates)}: "
                f"{[p.name for p in candidates]})")
        from ...engine import item_modifier as IM
        p = candidates[0]
        cur = edited.get(p) or p.read_bytes()
        try:
            for modifier, stat in stats.items():
                cur = IM.set_modifier_stat(cur, modifier, stat)
        except IM.ItemModifierError as e:
            raise ContentError(f"talent {mod_id}/{defn.id}: {e}") from e
        edited[p] = cur
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
