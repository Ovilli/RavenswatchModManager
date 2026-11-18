"""Ability edits declared in a manifest, applied to a hero's entity family.

A custom hero (``kind = "hero"``) lists its edits as ``[[content.abilities]]``
steps, applied in order to the BASE hero's entities, by the part names
``rsmm entity-graph <Base>`` shows. The hero kind then renames the family, so
the edits land in the hero's own entities and no other hero is touched.

One step per table::

    clone = "Ability Secondary"           a group, or a list of parts
    as = "Echo"                           new group name (required for a group)
    suffix = " Echo"                      appended to every copied part's name
                                          (default: " " + as)
    rename = { "Step 2" = "Step 3" }      exact new names for some copies (the
                                          rest take the suffix)
    from = "Juliet"                       copy from another hero's entity, or
                                          any entity by its path under
                                          EntitySettings ("Objects/Magical_Objects/
                                          Common/Dash_Crit_Chance")

    set = "Primary Ability Shots Delay.value"
    value = 0.2                           a number, bool or [x, y, z]; a number
                                          linked to another part becomes this
                                          literal (the link is dropped)

    set = "My Spawner.position[8]"        the n-th number inside an object
    value = 1.5708                        field (the spawn's yaw, radians)

    link = "Primary Ability Shoot Timer.on_end"
    to = "State Secondary Ability"        "" points it at nothing

    add_link = "State Secondary Ability.activates"
    to = "Secondary Ability Clip Echo"

    remove_link = "State Secondary Ability.activates[0]"

    remove_link = "On Damage Received.activates"    the same, by what it points at:
    to = "Modifier"                       steady when other steps change the order

    percent = "Descripton Format.obj_4"   a card slot shown x100 as a percentage
    value = true                          (false: the plain number)

    retarget = "My Spawner Value"         point the part's link into ANOTHER
    node = "Heroes\\Hero_Kintaro\\Hero_Kintaro_Special_Delayed_AOE.entity.ot|Radius"
                                          entity at that node (a spawner value's
                                          target: the spawned entity's number)

    add_subobject = "Wolf Basic Attack Combo.bytes_4"   append a copy of entry
    donor_index = 1                       ``donor_index`` of that id list (a
    replace_ref = { "Step 2" = "Step 3" } combo's steps), its links to the
                                          named parts re-pointed

``entity = "FX"`` (or a full stem) on any step targets another member of the
family, e.g. ``Hero_Piper_FX``; the default is the gameplay entity.

After the last step every edited entity goes through ``entity_check``: an
error (a link into an entity this hero does not carry, a sub-object with no
owner, ...) stops the apply rather than install an ability that does nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import entity_check as CK
from .entity_graph_edit import EntityEditError, EntityFile, id_list_pad

_OPS = ("clone", "set", "link", "add_link", "remove_link", "percent", "add_subobject",
        "replace_subobject", "switch_off", "override", "retarget", "retarget_targets", "event",
        "append_operand", "add_cinebloc", "animatic_speed", "animatic_clip", "add_selector",
        "unlink_reads", "swap_ref", "scale_by_talent", "talent_number", "owner_read",
        "add_status", "scale_with_level", "level_linear", "sound_volume")
#: Every key a step may carry; anything else is a typo that would otherwise be
#: ignored silently (a `rename` the old clone did not read left its copies
#: under the default suffix, and the next step found nothing).
_KEYS = {*_OPS, "value", "base", "to", "entity", "as", "suffix", "from", "rename",
         "donor_index", "donor", "replace_ref", "node", "from_kind", "when", "talent",
         "values", "tag", "percent", "flag", "switch", "duration", "status", "factor"}


class AbilityEditError(ValueError):
    pass


@dataclass
class Result:
    files: dict[str, bytes]                     # stem -> edited bytes
    resources: set[str] = field(default_factory=set)   # new resources to preload
    warnings: list[str] = field(default_factory=list)


def source_entity_ref(name: str) -> str:
    """A clone's ``from``: a hero name, or an entity path under EntitySettings."""
    if "/" not in name and "\\" not in name:
        return hero_entity_ref(name)
    p = name.replace("/", "\\").strip("\\")
    p = p.removeprefix("EntitySettings\\")
    return p if p.endswith(".entity.ot") else p.removesuffix(".entity") + ".entity.ot"


def hero_entity_ref(name: str) -> str:
    """``Juliet`` / ``Hero_Juliet`` -> ``Heroes\\Hero_Juliet\\Hero_Juliet.entity.ot``."""
    stem = name if name.startswith("Hero_") else f"Hero_{name}"
    return f"Heroes\\{stem}\\{stem}.entity.ot"


def apply(files: dict[str, bytes], steps: list[dict], *, main: str, seed: str,
          read=None, aliases: dict[bytes, str] | None = None,
          refs: dict[str, str] | None = None) -> Result:
    """Apply ``steps`` to ``files`` (entity stem -> bytes, the base family).
    ``aliases`` (alias GUID -> entity ref) lets an override reach an ancestor
    the entity inherits by alias (a hero written from scratch reaches
    Hero_Common and Character_Common only that way)."""
    read = read or CK._corpus_reader
    edits: dict[str, EntityFile] = {}

    def member(step: dict) -> EntityFile:
        want = str(step.get("entity") or main)
        stem = want if want in files else f"{main}_{want}"
        if stem not in files:
            raise AbilityEditError(f"no family entity {want!r}; have {', '.join(sorted(files))}")
        if stem not in edits:
            edits[stem] = EntityFile(files[stem], stem)
        return edits[stem]

    for n, step in enumerate(steps, 1):
        if not isinstance(step, dict):
            raise AbilityEditError(f"ability step {n} is not a table")
        ops = [op for op in _OPS
               if op in step and not (op == "percent" and isinstance(step[op], bool))]
        if len(ops) != 1:
            raise AbilityEditError(f"ability step {n} needs exactly one of {', '.join(_OPS)}")
        unknown = set(step) - _KEYS
        if unknown:
            raise AbilityEditError(f"ability step {n} has no key {', '.join(sorted(unknown))}")
        op = ops[0]
        try:
            ef = member(step)
            if op == "clone":
                _clone(ef, step, f"{seed}:{n}", read)
            elif op == "add_subobject":
                _add_subobject(ef, step, read)
            elif op == "replace_subobject":
                _replace_subobject(ef, step, read)
            elif op == "switch_off":
                # A damage debuff entry that never applies, kept in its list.
                part, fld, i = _list_entry(ef, str(step["switch_off"]), "switch_off")
                if i is None:
                    raise AbilityEditError("switch_off names one entry: 'Part.field[i]'")
                ef.switch_off_subobject(part, fld, i)
            elif op == "event":
                # A new empty one-frame event state (a trigger), for a file
                # that has none of its own to clone.
                from . import talent_writer as TW
                TW.TalentWriter(ef, f"{seed}:{n}", "Kit").state(str(step["event"]),
                                                                 flags=TW.EVENT)
            elif op == "override":
                _override(ef, step, f"{seed}:{n}", read, aliases)
            elif op == "retarget":
                _retarget(ef, step, read)
            elif op == "add_cinebloc":
                if not step.get("to") or "value" not in step:
                    raise AbilityEditError("add_cinebloc needs to = <part> and value = <start>")
                ef.add_cinebloc(str(step["add_cinebloc"]), str(step["to"]), float(step["value"]))
            elif op == "animatic_speed":
                if "value" not in step:
                    raise AbilityEditError("animatic_speed needs value = <rate>")
                ef.set_animatic_speed(str(step["animatic_speed"]), float(step["value"]))
            elif op == "animatic_clip":
                if not step.get("value"):
                    raise AbilityEditError("animatic_clip needs value = <fbx path>")
                _animatic_clip(ef, str(step["animatic_clip"]), str(step["value"]))
            elif op == "add_selector":
                if not step.get("to") or not step.get("when"):
                    raise AbilityEditError("add_selector needs to = <part> and when = <condition>")
                ef.prepend_selector_entry(
                    str(step["add_selector"]), str(step["to"]), str(step["when"]))
            elif op == "unlink_reads":
                from . import hero_ability as HA
                HA._unlink_value_reads(ef, str(step["unlink_reads"]))
            elif op == "swap_ref":
                if not step.get("node") or not step.get("to"):
                    raise AbilityEditError("swap_ref needs node = <old part> and to = <new part>")
                old = _source(ef, step, read).component(str(step["node"])).guid
                ef.swap_refs(str(step["swap_ref"]), old, str(step["to"]),
                             subobjects=True, cross_kind=True)
            elif op == "scale_by_talent":
                edits[ef.name] = _scale_by_talent(ef, step, f"{seed}:{n}")
            elif op == "talent_number":
                edits[ef.name] = _talent_number(ef, step, f"{seed}:{n}")
            elif op == "owner_read":
                _owner_read(ef, step, f"{seed}:{n}", files, edits, main, refs)
            elif op == "add_status":
                _add_status(ef, step, f"{seed}:{n}", read)
            elif op == "scale_with_level":
                if "value" not in step:
                    raise AbilityEditError("scale_with_level needs value = <ratio>")
                _scale_with_level(ef, str(step["scale_with_level"]), float(step["value"]),
                                  f"{seed}:{n}")
            elif op == "level_linear":
                if "value" not in step:
                    raise AbilityEditError(
                        "level_linear needs value = <per_level> (and optional base = <offset>)"
                    )
                _level_linear(ef, str(step["level_linear"]), float(step["value"]),
                              float(step.get("base", 0.0)), f"{seed}:{n}")
            elif op == "sound_volume":
                if "value" not in step:
                    raise AbilityEditError("sound_volume needs value = <float>")
                _sound_volume(ef, str(step["sound_volume"]), float(step["value"]))
            elif op == "append_operand":
                if not step.get("to"):
                    raise AbilityEditError("append_operand needs to = <part>")
                ef.append_operand(str(step[op]), str(step["to"]))
            elif op == "retarget_targets":
                part, _, fld = str(step[op]).rpartition(".")
                if not part or not step.get("to"):
                    raise AbilityEditError("retarget_targets = 'Sender.targets', to = <spawner>")
                to = step["to"]
                if not isinstance(to, str) and not (
                        isinstance(to, list) and to and all(isinstance(t, str) for t in to)):
                    raise AbilityEditError("retarget_targets to = <spawner> or [<spawner>, ...]")
                ef.repoint_targets(part, fld, to)
            else:
                spec = str(step[op])
                if ".cinebloc[" in spec:
                    part, _, fld = spec.partition(".cinebloc[")
                    fld = "cinebloc[" + fld
                else:
                    part, _, fld = spec.rpartition(".")
                if not part:
                    raise AbilityEditError(f"{op} = {step[op]!r}: write it as 'Part.field'")
                if op == "set":
                    if "value" not in step:
                        raise AbilityEditError("set needs a value")
                    ef.set_value(part, fld, step["value"])
                elif op == "link":
                    ef.set_ref(part, fld, str(step.get("to") or "") or None)
                elif op == "add_link" and step.get("from"):
                    # A part of an entity this one inherits (Hero_Alt_Form_
                    # Common's "State Anim Split Alt Form Enable"): by identity.
                    from .entity_graph_edit import kind_label
                    src = _source(ef, step, read)
                    want = str(step["to"])
                    hits = [c for c in src.graph().components if c.name == want]
                    if len(hits) != 1:
                        raise AbilityEditError(f"add_link: {src.name} has {len(hits)} parts "
                                               f"named {want!r}")
                    t = hits[0]
                    label = (f"[{kind_label(t.cls)}] {src.name}\\"
                             + (f"{t.group}\\" if t.group else "") + t.name)
                    ef.add_external_ref(part, fld, t.guid, label)
                elif op == "add_link":
                    ef.add_ref(part, fld, str(step["to"]))
                elif op == "percent":
                    if not isinstance(step.get("value", True), bool):
                        raise AbilityEditError("percent takes value = true or false")
                    ef.set_format_mode(part, fld, step.get("value", True))
                else:
                    base, _, idx = fld.partition("[")
                    if idx:
                        ef.remove_ref(part, base, int(idx.rstrip("]")))
                    elif step.get("to"):
                        ef.remove_ref(part, base, _link_index(ef, part, base, str(step["to"])))
                    else:
                        raise AbilityEditError("remove_link names an element: 'Part.list[i]', "
                                               "or 'Part.list' with to = the part it points at")
        except (EntityEditError, KeyError, ValueError) as e:
            raise AbilityEditError(f"ability step {n} ({op}): {e}") from e

    out = Result(dict(files))
    edited_map: dict[str, bytes] = {}
    for stem, ef in edits.items():
        try:
            edited_map[stem] = ef.to_bytes()
        except EntityEditError as e:
            raise AbilityEditError(f"the ability edits to {stem} do not hold together: {e}") from e
    by_ref = {refs[s]: b for s, b in edited_map.items() if refs and s in refs}

    def check_read(ref: str):
        stem = ref.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
        return by_ref.get(ref) or edited_map.get(stem) or read(ref)

    for stem, edited in edited_map.items():
        issues = CK.check(edited, files[stem], name=stem, read=check_read)
        errs = list(CK.errors(issues))
        if errs:
            raise AbilityEditError(
                f"the ability edits to {stem} do not hold together:\n  "
                + "\n  ".join(map(str, errs)))
        out.warnings += [f"{stem}: {i}" for i in issues
                         if not i.error and "no preload cache" not in i.message]
        out.resources |= CK.resource_paths(edited) - CK.resource_paths(files[stem])
        out.files[stem] = edited
    return out


def _link_index(ef: EntityFile, part: str, field: str, to: str) -> int:
    """The position in ``part``'s reference list ``field`` of the link to ``to``."""
    from . import entity_fields as EF
    f = next((x for x in EF.fields(ef.component(part)) if x.name == field), None)
    if f is None or f.kind != "ref[]":
        raise AbilityEditError(f"{part!r} has no reference list {field!r}")
    hits = [i for i, x in enumerate(f.items)
            if x.text.rstrip().rsplit("\\", 1)[-1].removesuffix('""') == to]
    if len(hits) != 1:
        have = ", ".join(x.text.rstrip().rsplit("\\", 1)[-1] for x in f.items) or "nothing"
        raise AbilityEditError(f"{part}.{field} links to {to!r} {len(hits)} times "
                               f"(it links to: {have})")
    return hits[0]


def _clone(ef: EntityFile, step: dict, seed: str, read) -> None:
    src = ef
    if step.get("from"):
        ref = source_entity_ref(str(step["from"]))
        raw = read(ref)
        if raw is None:
            raise AbilityEditError(f"no entity {ref}")
        src = EntityFile(raw, ref.rsplit("\\", 1)[-1][:-len(".entity.ot")])
    what = step["clone"]
    new_group = str(step.get("as") or "")
    groups = src.graph().groups()
    if isinstance(what, str) and what in groups:
        if not new_group:
            raise AbilityEditError(f"cloning group {what!r} needs 'as' (its new name)")
        names = [c.name for c in groups[what]]
        regroup = {what: new_group}
    else:
        names = [what] if isinstance(what, str) else [str(x) for x in what]
        regroup = {}
    # A copy keeps its source's override mark: copying an override (Scarlet's
    # "Event Initialize Starting Modifiers", an override of Character_Common's)
    # yields a second override of the same ancestor part, which REPLACES it
    # instead of adding a part. Every Kit Pet state made that way was missing
    # from the live hero (probe, 2026-11-03).
    by_name = {c.name: c for c in src.graph().components}
    overrides = [x for x in names if not regroup
                 and x in by_name and by_name[x].override is not None]
    if overrides:
        verb = "is an override" if len(overrides) == 1 else "are overrides"
        raise AbilityEditError(
            f"clone: {', '.join(overrides)} {verb}"
            " of an ancestor's part; a copy would replace that part, not add one. "
            "Copy a part of the entity's own, or use `override` to change the ancestor's")
    suffix = str(step.get("suffix", f" {new_group}" if new_group else " Copy"))
    rename = step.get("rename") or {}
    if not isinstance(rename, dict) or set(rename) - set(names):
        raise AbilityEditError(f"rename maps copied parts to new names; it names "
                               f"{', '.join(sorted(set(rename) - set(names))) or rename!r}, "
                               "which this clone does not copy")
    ef.clone(names, rename={x: str(rename.get(x, x + suffix)) for x in names},
             group=regroup, seed=seed,
             source=None if src is ef else src)


def _animatic_clip(ef: EntityFile, part: str, clip: str) -> None:
    """Swap an animatic's `.fbx` clip path and match its duration to the clip."""
    import re

    from . import hero_frame as HF
    c = ef.component(part)
    if c.cls != "oCEntityCpntAnimaticSettings":
        raise AbilityEditError(f"{part!r} is a {c.cls}, not an Animatic")
    old = re.search(rb"Characters\\[ -~]*?\.fbx", c.body)
    if old is None:
        raise AbilityEditError(f"{part!r} holds no animation clip path")
    HF.replace_in_slot(ef, part, old.group(0).decode(), clip)
    length = HF.clip_length(clip)
    if length:
        HF._set_duration(ef, part, length)


def _scale_by_talent(ef: EntityFile, step: dict, seed: str) -> EntityFile:
    """Scale one or more value/multiply nodes by a talent's per-rarity factor."""
    from . import talent_range as TR
    targets = step["scale_by_talent"]
    nodes = [targets] if isinstance(targets, str) else [str(x) for x in targets]
    if step.get("factor"):
        if not nodes:
            raise AbilityEditError("scale_by_talent with factor needs at least one target node")
        raw = ef.to_bytes()
        factor_name = str(step["factor"])
    else:
        if not step.get("talent") or "values" not in step:
            raise AbilityEditError("scale_by_talent needs talent = <name> and values = [...]")
        tag = str(step.get("tag") or "Attack")
        percent = bool(step.get("percent", True))
        raw, factor = TR.add_factor(ef.to_bytes(), talent=str(step["talent"]),
                                    values=step["values"], tag=tag, percent=percent, seed=seed)
        factor_name = factor.name
    for node in nodes:
        raw = TR.scale_node(raw, node=node, factor=factor_name,
                            seed=f"{seed}:{node}", scope=ef.name)
    return EntityFile(raw, ef.name)


def _sound_volume(ef: EntityFile, part: str, volume: float) -> None:
    """Set the Volume scalar on an oCEntityCpntFModEventSettings component."""
    import struct
    c = ef.component(part)
    if c.cls != "oCEntityCpntFModEventSettings":
        raise AbilityEditError(f"{part!r} is a {c.cls}, not an FMod event")
    obj = ef.objects[c.index - 1]
    marker = b"\x22\x22\xbb\xaa\x22\x22\xbb\xaa\x11\x11\xbb\xaa\x0b"
    p = bytes(obj).rfind(marker)
    if p < 0 or p + 45 > len(obj) or obj[p + 16] != 0 \
            or bytes(obj[p + 25:p + 29]) != b"\x00\x00\x00\x00" \
            or bytes(obj[p + 37:p + 45]) != b'""\xbb\xaa""\xbb\xaa':
        raise AbilityEditError(f"{part!r}: unexpected FModEventSettings volume layout")
    struct.pack_into("<f", obj, p + 33, float(volume))


def _talent_number(ef: EntityFile, step: dict, seed: str) -> EntityFile:
    """Create a per-rarity value node for ``talent``, bind it on the card, and optionally a flag."""
    from . import entity_graph as EG
    from . import talent_add_stat as TA
    from . import talent_status as TS
    from . import talent_writer as TW

    if not step.get("talent") or "values" not in step:
        raise AbilityEditError("talent_number needs talent = <name> and values = [...]")
    talent = str(step["talent"])
    name = str(step["talent_number"])
    raw = ef.to_bytes()
    if step.get("flag"):
        raw, _ = TS.add_flag(raw, talent=talent, seed=seed)
    ctl, _st, fmt = TA.card_parts(EG.parse(raw), talent)
    ef2 = EntityFile(raw, ef.name)
    w = TW.TalentWriter(ef2, f"{seed}:num:{name}", f"Skill {talent}")
    sel_name = f"{name} Selector"
    sel = w.rarity(sel_name, TW.link_to(ef2, ctl.name), TA.normalise_values(step["values"]))
    w.value_of(name, sel)
    if fmt:
        ef2.add_format_slot(fmt.name, sel_name, percent=bool(step.get("percent", False)))
    return ef2


def _owner_read(ef: EntityFile, step: dict, seed: str, files: dict[str, bytes],
                edits: dict[str, EntityFile], main: str, refs: dict[str, str] | None) -> None:
    """Add a GetValue node on a spawned/child entity reading a value from its owner."""
    from . import entity_parts as P
    from . import talent_status as TS
    from . import talent_writer as TW
    from .entity_graph_edit import kind_label

    if not step.get("node"):
        raise AbilityEditError("owner_read needs node = <owner part>")
    owner_stem = str(step.get("from") or main)
    if owner_stem not in files:
        owner_stem = f"{main}_{owner_stem}"
    if owner_stem not in files:
        raise AbilityEditError(f"owner_read: no entity {step.get('from') or main!r}")
    owner_ef = edits.get(owner_stem) or EntityFile(files[owner_stem], owner_stem)
    t = owner_ef.component(str(step["node"]))
    label = f"[{kind_label(t.cls)}] {owner_stem}\\" + (f"{t.group}\\" if t.group else "") + t.name
    owner_ref = (refs or {}).get(owner_stem) or hero_entity_ref(owner_stem)
    name = str(step["owner_read"])
    TW.TalentWriter(ef, seed, "").reader(
        name, owner_ref, P.Link(t.guid, label), owners=(0,), walk_owners=True)
    have = {c.name for c in ef.graph().components}
    init = (TS.startup_state(ef.graph(), owner_ref, but=name)
            or next((n for n in ("Child Event Initialize", "Event Initialize") if n in have), None))
    if init is None:
        raise AbilityEditError("owner_read: no start-up state to activate reader")
    ef.insert_ref(init, "activates", 0, name)


def _add_status(ef: EntityFile, step: dict, seed: str, read) -> None:
    """Attach a talent-gated status debuff (including Marked) to one or more damage parts."""
    from . import talent_status as TS

    if not step.get("status") or not step.get("switch") or not step.get("talent"):
        raise AbilityEditError("add_status needs status, switch, and talent")
    raw_targets = step["add_status"]
    targets = [raw_targets] if isinstance(raw_targets, str) else [str(x) for x in raw_targets]
    status, switch, talent = str(step["status"]), str(step["switch"]), str(step["talent"])
    dur = str(step.get("duration") or "")
    if status == "Marked":
        jraw = read(hero_entity_ref("Juliet"))
        if jraw is None:
            raise AbilityEditError("add_status Marked: Hero_Juliet is not in the game files")
        jef = EntityFile(jraw, "Hero_Juliet")
        jmod = jef.component("Skill Ultimate 2 Marked Modifier")
        obj = TS.debuff_of(jraw, jmod.name)
        for dmg in targets:
            mod = f"Skill {talent} Marked On {dmg}"
            ef.clone([jmod.name], rename={jmod.name: mod},
                     group={jmod.group: ef.component(dmg).group}, source=jef, seed=f"{seed}:{dmg}")
            if dur:
                ef.set_ref(mod, "duration", dur)
            ef.add_subobject(dmg, "bytes_36", jef, obj, refs={jmod.guid: mod}, switch=switch)
        return
    def_ef, def_raw = TS.donor_of(status)
    for dmg in targets:
        TS.add_status(ef, def_ef, def_raw, damage=dmg, status=status,
                      switch=switch, talent=talent, seed=seed)


def _scale_with_level(ef: EntityFile, target: str, ratio: float, seed: str) -> None:
    """Make ``target``'s amount/value equal ``ratio * owner's Level Damage``."""
    from . import entity_parts as P
    from . import talent_add_stat as TA
    from . import talent_range as TR
    from . import talent_writer as TW

    c = ef.component(target)
    slot = 1 if c.cls == "oCEntityCpntModifierSettings" else 0
    reader_name = "Owner Level Damage"
    level_dmg = P.Link(bytes.fromhex("351a83c831da0b4ebd0716d89160d84d"),
                       r"[Value] Character_Common\Base\Level Damage")
    if not any(x.name == reader_name for x in ef.graph().components):
        TW.TalentWriter(ef, f"{seed}:level-dmg", "").reader(
            reader_name, r"Heroes\Hero_Common\Hero_Common.entity.ot",
            level_dmg, owners=(0,), walk_owners=True)
        startup = TA._startup_state(ef)
        if startup is not None:
            ef.insert_ref(startup, "activates", 0, reader_name)
    w = TW.TalentWriter(ef, f"{seed}:level:{target}", c.group)
    ratio_link = w.add(TW._VALUE, f"{target} Level Ratio",
                       {"value": P.Num.f32(ratio), "flag": 0}, flags=0x101)
    scaled_name = f"{target} Level Scaled"
    w.multiply(scaled_name, TW.link_to(ef, reader_name),
               ef.F32_ACCESSOR["oCEntityCpntGetValueSettings"],
               ratio_link, TW.READ_VALUE, group=c.group)
    ef.source_value(target, slot, scaled_name)
    if TR._activate_before(ef, target, [scaled_name]) == 0:
        startup = TA._startup_state(ef)
        if startup is not None:
            ef.add_ref(startup, "activates", scaled_name)


def _level_linear(ef: EntityFile, target: str, per_level: float, base: float,
                  seed: str) -> None:
    """Make ``target``'s amount/value equal ``base + per_level * Current XP Level``."""
    from . import entity_parts as P
    from . import talent_add_stat as TA
    from . import talent_range as TR
    from . import talent_writer as TW

    c = ef.component(target)
    slot = 1 if c.cls == "oCEntityCpntModifierSettings" else 0
    xp_level = P.Link(bytes.fromhex("81e2538eaf800d4a894aa88ffec17b03"),
                      r"[Value] Character_Common\Base\Current XP Level")
    w = TW.TalentWriter(ef, f"{seed}:lvl-lin:{target}", c.group)
    per_link = w.add(TW._VALUE, f"{target} Per Level",
                     {"value": P.Num.f32(per_level), "flag": 0}, flags=0x101)
    mul_name = f"{target} Level Mul"
    mul_link = w.multiply(mul_name, xp_level,
                          ef.INT_ACCESSOR["oCEntityCpntValueSettings"],
                          per_link, TW.READ_VALUE, group=c.group, a_num=P.Num.int(0))
    sum_name = f"{target} Level Linear"
    w.sum_op(sum_name, base,
             terms=[(mul_link, ef.F32_ACCESSOR["oCEntityCpntValueOperationsSettings"])],
             group=c.group)
    ef.source_value(target, slot, sum_name)
    if TR._activate_before(ef, target, [mul_name, sum_name]) == 0:
        startup = TA._startup_state(ef)
        if startup is not None:
            ef.add_ref(startup, "activates", mul_name)
            ef.add_ref(startup, "activates", sum_name)


def _source(ef: EntityFile, step: dict, read) -> EntityFile:
    """The entity a step copies from: ``from`` (a hero or an entity path), or
    the one it edits."""
    if not step.get("from"):
        return ef
    ref = source_entity_ref(str(step["from"]))
    raw = read(ref)
    if raw is None:
        raise AbilityEditError(f"no entity {ref}")
    return EntityFile(raw, ref.rsplit("\\", 1)[-1][:-len(".entity.ot")])


def _list_entry(ef: EntityFile, spec: str, what: str) -> tuple[str, str, int | None]:
    """``Part.field[i]`` (or ``Part.field``) -> part, field, i."""
    part, _, fld = spec.rpartition(".")
    if not part:
        raise AbilityEditError(f"{what} names 'Part.field[i]' (an id list entry)")
    fld, _, idx = fld.partition("[")
    if not idx:
        return part, fld, None
    try:
        return part, fld, int(idx.rstrip("]"))
    except ValueError:
        raise AbilityEditError(f"{what} = {spec!r}: the index must be a number") from None


def _list_ids(ef: EntityFile, part: str, fld: str) -> list[int]:
    from . import entity_fields as EF
    c = ef.component(part)
    f = next((x for x in EF.fields(c) if x.name == fld), None)
    if f is None:
        raise AbilityEditError(f"{part!r} has no field {fld!r}")
    pad = id_list_pad(c.cls, fld)
    n = int.from_bytes(c.body[f.offset + pad:f.offset + pad + 4], "little")
    if f.size != pad + 4 + 4 * n:
        raise AbilityEditError(f"{part}.{fld} is not an id list")
    return [int.from_bytes(c.body[f.offset + pad + 4 + 4 * i:f.offset + pad + 8 + 4 * i], "little")
            for i in range(n)]


def _donor(ef: EntityFile, step: dict, read, part: str, fld: str) -> tuple[EntityFile, int, dict]:
    """The sub-object a step copies and its re-pointed links: ``donor =
    'Part.field[i]'`` in ``from`` (or this entity), else entry ``donor_index``
    of the edited list itself. ``replace_ref`` keys are the donor's part names,
    values this entity's."""
    src = _source(ef, step, read)
    if step.get("donor") is not None:
        dpart, dfld, i = _list_entry(src, str(step["donor"]), "donor")
        if i is None:
            raise AbilityEditError("donor names one entry: 'Part.field[i]'")
    elif src is ef:
        dpart, dfld, i = part, fld, step.get("donor_index")
    else:
        raise AbilityEditError("copying from another entity needs donor = 'Part.field[i]'")
    ids = _list_ids(src, dpart, dfld)
    if isinstance(i, bool) or not isinstance(i, int) or not 0 <= i < len(ids):
        raise AbilityEditError(f"donor: {dpart}.{dfld} has entries 0..{len(ids) - 1}")
    refs = {src.component(str(old)).guid: str(new)
            for old, new in (step.get("replace_ref") or {}).items()}
    return src, ids[i], refs


def _add_subobject(ef: EntityFile, step: dict, read) -> None:
    """Append a copy of a sub-object (``_donor``) to id list ``Part.field``."""
    part, fld, i = _list_entry(ef, str(step["add_subobject"]), "add_subobject")
    if i is not None:
        raise AbilityEditError("add_subobject appends: name the list, 'Part.field'")
    src, obj, refs = _donor(ef, step, read, part, fld)
    ef.add_subobject(part, fld, src, obj, refs=refs)


def _replace_subobject(ef: EntityFile, step: dict, read) -> None:
    """Put a copy of a sub-object (``_donor``) in place of entry
    ``Part.field[i]``: same list position, so whatever selects that entry
    (an Fx selector's slot) now gets the copy."""
    part, fld, i = _list_entry(ef, str(step["replace_subobject"]), "replace_subobject")
    if i is None:
        raise AbilityEditError("replace_subobject names one entry: 'Part.field[i]'")
    src, obj, refs = _donor(ef, step, read, part, fld)
    ef.replace_subobject(part, fld, i, src, obj, refs=refs)


def _override(ef: EntityFile, step: dict, seed: str, read,
              aliases: dict[bytes, str] | None = None) -> None:
    """Give this entity its own version of an ANCESTOR's part: a copy marked as
    that part's override, so the engine builds it INSTEAD of the ancestor's
    (a plain clone would be a second part built next to it). ``from`` is the
    ancestor; ``set`` steps then change the copy."""
    from .entity_check import _ancestors
    from .entity_graph_edit import kind_label
    name = str(step["override"])
    if not step.get("from"):
        raise AbilityEditError("override needs from = the ancestor entity that has the part")
    src = _source(ef, step, read)
    hits = [c for c in src.graph().components if c.name == name]
    if len(hits) != 1:
        raise AbilityEditError(f"override: {src.name} has {len(hits)} parts named {name!r}")
    anc = hits[0]
    if _ancestors(ef.to_bytes(), read, aliases).get(anc.guid) != src.name:
        raise AbilityEditError(f"override: {src.name} is not an ancestor of {ef.name}; "
                               "an override of it would never apply")
    if any(c.name == name or (c.override and c.override.guid == anc.guid)
           for c in ef.graph().components):
        raise AbilityEditError(f"override: {ef.name} already has a part {name!r} "
                               "(set it directly)")
    ef.clone([name], rename={name: name}, seed=seed, source=src)
    path = anc.path if anc.group else anc.name
    ef.set_override(name, anc.guid, f"[{kind_label(anc.cls)}] {src.name}\\{path}")


def _retarget(ef: EntityFile, step: dict, read) -> None:
    """Point ``retarget``'s link into another entity at ``node``
    (``<entity ref>|<part name>``): its links of that node's kind that lead
    outside this file move there (a spawner value's ``target_value``)."""
    from . import entity_graph as EG
    from .entity_graph_edit import kind_label
    ref, _, name = str(step.get("node") or "").partition("|")
    ref_path = source_entity_ref(ref) if ref and name else ""
    raw = read(ref_path) if ref_path else None
    if raw is None:
        raise AbilityEditError(f"retarget: no entity {ref!r} (node is '<entity>|<part>')")
    stem = ref_path.rsplit("\\", 1)[-1].removesuffix(".entity.ot")
    hits = [c for c in EG.parse(raw, stem).components if c.name == name]
    if len(hits) != 1:
        raise AbilityEditError(f"retarget: {stem} has {len(hits)} parts named {name!r}")
    node = hits[0]
    kind = kind_label(node.cls)
    label = f"[{kind}] {stem}\\" + (f"{node.group}\\" if node.group else "") + node.name
    # `Part.field` names the link (a spawner value's `target_value`): whatever
    # it holds now, inside this file or out, moves. Plain `Part`: its links of
    # that kind (or `from_kind` when moving between compatible 3d node types)
    # leading outside this file.
    pname, _, fld = str(step["retarget"]).partition(".")
    part = ef.component(pname)
    if fld:
        # Written whatever it held: a spawner value's target can be empty.
        from .hero_kit import point
        point(ef, pname, fld, node.guid, label)
        return
    src_kind = str(step.get("from_kind") or kind)
    mine = {c.guid for c in ef.graph().components}
    prefix = f"[{src_kind}] "
    old = [r.guid for r in part.refs if r.guid not in mine and r.path.startswith(prefix)]
    subobjects = False
    if not old:
        classes = [c.name for c in ef.cf.classes]
        picker_cls = classes.index("oCEntityCpntPicker") if "oCEntityCpntPicker" in classes else -1
        if picker_cls >= 0:
            for o in sorted(ef.subtree({part.index - 1})):
                old.extend(r.guid for _, r in EG._pickers(bytes(ef.objects[o]), picker_cls)
                           if r.guid not in mine and r.path.startswith(prefix))
        subobjects = bool(old)
    if not old:
        raise AbilityEditError(f"retarget: {part.name!r} has no outside {src_kind} link to move")
    acc = ef.VEC3_ACCESSOR.get(node.cls) if src_kind != kind else None
    for g in dict.fromkeys(old):
        ef.retarget_external(part.name, g, node.guid, label,
                             subobjects=subobjects, cross_kind=src_kind != kind,
                             accessor=acc)
