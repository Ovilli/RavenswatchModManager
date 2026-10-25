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

``entity = "FX"`` (or a full stem) on any step targets another member of the
family, e.g. ``Hero_Piper_FX``; the default is the gameplay entity.

After the last step every edited entity goes through ``entity_check``: an
error (a link into an entity this hero does not carry, a sub-object with no
owner, ...) stops the apply rather than install an ability that does nothing.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from . import entity_check as CK
from .entity_graph_edit import EntityEditError, EntityFile

_OPS = ("clone", "set", "link", "add_link", "remove_link", "percent")


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
          read=None) -> Result:
    """Apply ``steps`` to ``files`` (entity stem -> bytes, the base family)."""
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
        ops = [op for op in _OPS if op in step]
        if len(ops) != 1:
            raise AbilityEditError(f"ability step {n} needs exactly one of {', '.join(_OPS)}")
        op = ops[0]
        try:
            ef = member(step)
            if op == "clone":
                _clone(ef, step, f"{seed}:{n}", read)
            else:
                part, _, fld = str(step[op]).rpartition(".")
                if not part:
                    raise AbilityEditError(f"{op} = {step[op]!r}: write it as 'Part.field'")
                if op == "set":
                    if "value" not in step:
                        raise AbilityEditError("set needs a value")
                    ef.set_value(part, fld, step["value"])
                elif op == "link":
                    ef.set_ref(part, fld, str(step.get("to") or "") or None)
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
    for stem, ef in edits.items():
        edited = ef.to_bytes()
        issues = CK.check(edited, files[stem], name=stem, read=read)
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
    suffix = str(step.get("suffix", f" {new_group}" if new_group else " Copy"))
    ef.clone(names, rename={x: x + suffix for x in names}, group=regroup, seed=seed,
             source=None if src is ef else src)
