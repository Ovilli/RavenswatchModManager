"""Make an ability's hits put a status on enemies while a talent is owned:
"ATTACK applies Ignite".

A status on hit is a DEBUFF of the ability's damage record: each damage record
(``oCEntityCpntDamageSettings``) keeps a list of ``oCDtDamageDebuffSettings``
sub-objects (``bytes_36``: u32 count + ids, at the same place in all 209 hero
damage records), and each debuff holds an on/off switch and the status
modifier to put on whoever is hit. Melusine's Freezing Splash is this shape:
her POWER caster's damage has a Chill debuff whose switch reads, through a
get-value node, a value in her hero file that reads the talent's owned state.

Built here:

1. **Flag**, in the file holding the talent: a true/false value reading the
   talent's owned state (written, ``talent_writer``, in the shape of Freezing
   Splash's ``Skill Power Chill Available``).
2. **Reader**: when the damage is in another entity of the hero (a caster, a
   projectile), a get-value node reads the flag (written, as Melusine's caster's
   is), switched on first thing by the entity's start-up state.
3. **Debuff**: a copy of a shipped debuff of the chosen status, with its status
   modifier, appended to the damage's debuff list; its switch reads the flag
   (hero file: the owned state itself) or the reader.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import entity_graph as EG
from . import entity_graph_edit as GE
from . import entity_parts as P
from . import talent_add_stat as TA
from . import talent_writer as TW


class StatusError(ValueError):
    """The status cannot be added this way; the message says why."""


@dataclass(frozen=True)
class Donor:
    rel: str                 # corpus path of the entity holding the debuff
    modifier: str            # the status modifier it puts on whoever is hit
    numbers: tuple = ()      # value nodes the modifier reads, copied with it


_ENT = ".entity.ot.EntitySettingsResource.gen"

#: A shipped debuff for each status, named as the game's stat registry names the
#: status. Each was picked (survey 2026-10-09, every debuff in the game) so its
#: modifier reads nothing outside itself and the ``numbers`` copied with it: no
#: talent rarity, no state, no other entity. Most hero debuffs fail that (Carmilla's
#: Bleed amount is an operation over her own values); Marked has no such donor.
DONORS: dict[str, Donor] = {
    "Chilled": Donor(f"EntitySettings/Heroes/Hero_Juliet/Hero_Juliet_Rose_Explosion{_ENT}",
                     "Skill Romeo Power Chilled Modifier"),
    "Ignite": Donor(f"EntitySettings/Heroes/Hero_Red/Hero_Red{_ENT}",
                    "Skill Ultimate 1 Fire Ignite Modifier"),
    "Bleed": Donor(f"EntitySettings/Character_Common/Character_Common{_ENT}",
                   "Shatter Applies BLEED Modifier", ("Shatter Bleed Value",)),
    "Vulnerable": Donor(f"EntitySettings/Character_Common/Character_Common{_ENT}",
                        "Shatter Applies VULNERABLE Modifier",
                        ("Shatter Applies Vulnerable Duration",)),
    "Weak": Donor(f"EntitySettings/Enemies/Knights/Knights_Model{_ENT}",
                  "Attack Soul Drain Weak Modifier"),
    "Rooted": Donor(f"EntitySettings/Enemies/Treant/Projectile_Treant_Root{_ENT}",
                    "Root Trap Attack Root Modifier"),
}
STATUSES = tuple(DONORS)

_DEBUFFS = "bytes_36"


def debuff_of(raw: bytes, modifier: str) -> int:
    """The id of the debuff sub-object in ``raw`` that applies ``modifier``."""
    ef = GE.EntityFile(raw)
    m = ef.component(modifier)
    hits = [i for i, p in enumerate(ef.objects)
            if ef._class(i) == "oCDtDamageDebuffSettings" and m.guid in p]
    if not hits:
        raise StatusError(f"no debuff applies {modifier!r} here")
    return hits[0]


def add_flag(raw: bytes, *, talent: str, seed: str = "") -> tuple[bytes, str]:
    """Return the file holding ``talent`` with a true/false value that is on
    while the talent is owned (step 1), and that value's name."""
    graph = EG.parse(raw)
    ctl = next((c for c in graph.components if c.name == f"Skill Controller {talent}"), None)
    if ctl is None:
        raise StatusError(f"no talent {talent!r} here")
    state = TA.owned_state(graph, ctl, talent)
    name = f"Skill {talent} Owned"
    if any(c.name == name for c in graph.components):
        return raw, name                       # one flag serves every status of the talent
    ef = GE.EntityFile(raw)
    try:
        TW.TalentWriter(ef, f"{seed or talent}:owned", f"Skill {talent}").value_of(
            name, TW.link_to(ef, state.name), flag=True)
        return ef.to_bytes(), name
    except (GE.EntityEditError, P.PartError) as e:
        raise StatusError(f"talent {talent!r}: {e}") from e


def startup_state(graph: EG.EntityGraph, owner_resource: str, *, but: str = "") -> str | None:
    """The state of a spawned entity whose ``activates`` list switches on its
    readers of the hero (``owner_resource``), or None: where a new reader must be
    switched on too. ``but`` is a reader to leave out of the count."""
    from . import entity_fields as EF
    readers = {c.guid for c in graph.components if c.cls.endswith("GetValueSettings")
               and owner_resource in "".join(c.literals) and c.name != but}
    best, most = None, 0
    for c in graph.components:
        f = next((x for x in EF.fields(c) if x.name == "activates" and x.kind == "ref[]"), None)
        if f is None:
            continue
        k = sum(c.body[it.offset + 8:it.offset + 24] in readers for it in f.items)
        if k > most:
            best, most = c.name, k
    return best


def reader(raw: bytes, *, flag_guid: bytes, flag_label: str, owner_resource: str,
           name: str, seed: str = "", scope: str = "") -> bytes:
    """Return ``raw`` (another entity of the hero) with a node ``name`` reading
    the flag from the hero (step 2), switched on first by the entity's start-up
    state (the list that switches on its other readers of the hero). ``scope`` is
    the entity's own name, for one whose references do not tell it."""
    ef = GE.EntityFile(raw, scope)
    if any(c.name == name for c in ef.graph().components):
        return raw
    try:
        TW.TalentWriter(ef, f"{seed}:owned", "").reader(
            name, owner_resource, P.Link(flag_guid, flag_label))
        best = startup_state(ef.graph(), owner_resource, but=name)
        if best is None:
            raise StatusError("no start-up state here switches on readers of the hero")
        ef.insert_ref(best, "activates", 0, name)
        return ef.to_bytes()
    except (GE.EntityEditError, P.PartError) as e:
        raise StatusError(str(e)) from e


def apply_status(raw: bytes, donor_raw: bytes, *, damage: str, status: str, switch: str,
                 talent: str, seed: str = "", scope: str = "") -> bytes:
    """Return ``raw`` with damage record ``damage`` also putting ``status`` on
    whoever it hits while ``switch`` (a state or true/false value of this file)
    is on (step 3)."""
    if status not in DONORS:
        raise StatusError(f"unknown status {status!r}; one of {', '.join(STATUSES)}")
    d = DONORS[status]
    ef = GE.EntityFile(raw, scope)
    c = ef.component(damage)
    if not c.cls.endswith("CpntDamageSettings"):
        raise StatusError(f"{damage!r} is not a damage record")
    donor = GE.EntityFile(donor_raw)
    obj = debuff_of(donor_raw, d.modifier)
    mod = f"Skill {talent} {status} On {damage}"
    if any(x.name == mod for x in ef.graph().components):
        raise StatusError(f"{damage!r} already applies {status} for {talent!r}")
    rename = {d.modifier: mod, **{n: f"{mod} {n}" for n in d.numbers}}
    groups = {donor.component(n).group: c.group for n in rename}
    try:
        ef.clone(list(rename), rename=rename, group=groups, source=donor,
                 seed=f"{seed}:{talent}:{status}:{damage}")
        ef.add_subobject(damage, _DEBUFFS, donor, obj,
                         refs={donor.component(d.modifier).guid: mod}, switch=switch)
        return ef.to_bytes()
    except GE.EntityEditError as e:
        raise StatusError(f"{damage!r}: {e}") from e


def damages(files: list[tuple[str, bytes]], hero: str) -> list[dict]:
    """``[{file, damage, ability, where}]``: the damage records of ``hero``'s
    abilities a status can be added to (the hero's own file, and entities that
    already read the hero), named by ability as ``talent_range.candidates``."""
    from .talent_range import _GROUP_ABILITY, reads_owner
    main = f"Hero_{hero}"
    owner = f"Heroes\\{main}\\{main}.entity.ot"
    out = []
    for stem, raw in files:
        if stem != main and not reads_owner(raw, owner):
            continue
        graph = EG.parse(raw)
        # A hit outside the hero's file is switched by a reader of the hero,
        # which only runs when the entity's start-up state switches it on
        # (Merlin's meteor reads the hero but switches no reader on).
        if stem != main and startup_state(graph, owner) is None:
            continue
        for c in graph.components:
            if not c.cls.endswith("CpntDamageSettings") or c.group.startswith("Skill"):
                continue
            ability = next((a for g, a in _GROUP_ABILITY if c.group.startswith(g)), None) \
                or next((a for g, a in _GROUP_ABILITY if c.name.startswith(g.split()[1] + " ")
                         or c.name.startswith(g)), None)
            out.append({"file": stem, "damage": c.name, "ability": ability,
                        "where": None if stem == main else stem.removeprefix(main + "_")})
    return out
