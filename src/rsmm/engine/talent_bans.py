"""Talent bans: keep chosen talents out of every offer, as the item ban does
for magical objects.

A talent card (a "Skill Controller <T>" in the hero's main entity) is dealt
only after it ACTIVATES: activation registers it into the hero's offer pool
(SkillController vftable slot 28, FUN_1402e8250), and every ordinary shipped
talent starts active (header flags 0x1000101). The game's own "registered but
never dealt" state is the same record with that bit clear: the ultimate
UPGRADE cards ship as 0x1000001 and are dealt only after their ultimate
activates them. Nothing activates an ordinary talent later, so clearing its
starts-active bit (``hero_frame.STARTS_ACTIVE``) keeps it out of every offer
while its card still shows in the compendium (which walks the controllers,
not the pools).

Data-level, install-time, deterministic: every peer running the mod builds
the same pools, so the seeded offer draw stays identical in co-op (a per-peer
runtime filter would desync it, the item ban's reason too).

POOLS. A controller's ``bytes_4`` picks its pool: 0 = the starting pick at run
start, 1 = level-up picks, 2 = ultimate powers, 3 = ultimate upgrades. Only
pools 0 and 1 are bannable. A pool left EMPTY blocks the run: the offer builder
deals from the first empty held slot's pool, so an empty starting pool closes
the pick window at once and every later pick with it (Jack, 2026-11-08). The
ban therefore refuses to leave fewer than ``MIN_LEFT[pool]`` talents.

Ids are ``"<HeroFolder>/<controller>"``: ``"Red/Basic Cleave"`` is Scarlet's
"Skill Controller Basic Cleave" (Cleave).
"""

from __future__ import annotations

import re
import struct
from dataclasses import dataclass
from functools import cache
from pathlib import Path

from . import corpus
from . import entity_fields as EF
from . import entity_graph as EG

HEROES_DIR = "EntitySettings/Heroes"
GEN_SUFFIX = ".entity.ot.EntitySettingsResource.gen"
CONTROLLER_CLASS = "oCDtEntityCpntSkillControllerSettings"
CONTROLLER_PREFIX = "Skill Controller "
#: Folders that are not playable heroes (shared bases, pets).
NOT_HEROES = {"Hero_Common", "Hero_Pets"}
#: Header bits: 0x1 = the component exists (shipped cut talents have it clear),
#: 0x100 = starts active (registers into the offer pool).
ENABLED, STARTS_ACTIVE = 0x1, 0x100
POOL_NAMES = {0: "starting pick", 1: "level-up"}
#: Fewest talents a pool may keep. 0 empties the pick and blocks the run; a
#: level-up offer deals three cards.
MIN_LEFT = {0: 1, 1: 3}

_TEXT = re.compile(r"'Text' '([^']+)' '([^']+)'")


class TalentBanError(ValueError):
    pass


@dataclass(frozen=True)
class Talent:
    id: str              # "Red/Basic Cleave"
    hero: str            # display name, "Scarlet"
    folder: str          # "Hero_Red"
    controller: str      # "Skill Controller Basic Cleave"
    pool: int            # 0 starting pick, 1 level-up
    name: str            # "Cleave"
    description: str     # the card text, with the game's markup


def main_file(folder: str) -> str:
    return f"{HEROES_DIR}/{folder}/{folder}{GEN_SUFFIX}"


@cache
def _bank(bank: str) -> dict[str, str]:
    """English text of a bank (key -> value), empty when unreadable."""
    from .text_patches import parse_text_bytes
    keys = corpus.read(f"Text/{bank}.LocalText.gen")
    vals = corpus.read(f"Text/{bank}.LocalText.gen.LangEN")
    if keys is None or vals is None:
        return {}
    try:
        k = parse_text_bytes(keys, Path(bank)).entries
        v = parse_text_bytes(vals, Path(bank)).entries
    except ValueError:
        return {}
    return dict(zip(k, v, strict=False))


def _pool(c: EG.Component) -> int | None:
    f = next((x for x in EF.fields(c) if x.name == "bytes_4"), None)
    if f is None or f.size < 4:
        return None
    return struct.unpack_from("<I", c.body, f.offset)[0]


def _card_text(c: EG.Component) -> tuple[str, str, str]:
    """(bank, name, description) from the controller's text keys."""
    for f in EF.fields(c):
        m = _TEXT.search(f.text)
        if m and m.group(2).endswith("_Name"):
            bank, key = m.group(1), m.group(2)
            text = _bank(bank)
            return bank, text.get(key, ""), text.get(key[:-len("_Name")] + "_Desc", "")
    return "", "", ""


def offerable(c: EG.Component) -> bool:
    return (c.cls == CONTROLLER_CLASS and c.name.startswith(CONTROLLER_PREFIX)
            and (c.flags & ENABLED) != 0 and (c.flags & STARTS_ACTIVE) != 0
            and _pool(c) in POOL_NAMES)


def hero_talents(folder: str) -> list[Talent]:
    """The bannable talents of one hero: shipped, offerable, named (a cut
    talent has an empty English name), in pools 0 and 1."""
    raw = corpus.read(main_file(folder))
    if raw is None:
        return []
    out = []
    hero = folder[len("Hero_"):]
    for c in EG.parse(raw, folder).components:
        if not offerable(c):
            continue
        bank, name, desc = _card_text(c)
        if not name.strip():
            continue
        display = _bank(bank).get("Hero_Name", "") or hero
        out.append(Talent(f"{hero}/{c.name[len(CONTROLLER_PREFIX):]}", display, folder,
                          c.name, _pool(c), name.strip(), desc))
    return out


def catalog() -> list[Talent]:
    """Every bannable talent of every shipped hero, by hero then pool then name."""
    out = []
    for folder in sorted(corpus.subdirs(HEROES_DIR)):
        if folder.startswith("Hero_") and folder not in NOT_HEROES:
            out += sorted(hero_talents(folder), key=lambda t: (t.pool, t.name.lower()))
    return out


def ban(ids: list[str], read=None) -> dict[str, bytes]:
    """Hero main entity files (corpus rel -> new bytes) with every talent in
    ``ids`` kept out of the offers. ``read(rel)`` gives the bytes to build on
    (default: the shipped file), so a ban composes with an earlier edit of the
    same file. Raises TalentBanError on an unknown id or a pool left too small."""
    from .entity_graph_edit import EntityFile
    from .hero_frame import set_starts_active
    by_folder: dict[str, list[str]] = {}
    for tid in dict.fromkeys(str(x) for x in ids):
        hero, _, ctl = tid.partition("/")
        if not hero or not ctl:
            raise TalentBanError(f"{tid!r}: a talent id is \"<Hero>/<controller>\", "
                                 "e.g. \"Red/Basic Cleave\"")
        by_folder.setdefault(f"Hero_{hero}", []).append(ctl)
    out: dict[str, bytes] = {}
    for folder, ctls in sorted(by_folder.items()):
        known = {t.controller: t for t in hero_talents(folder)}
        if not known:
            raise TalentBanError(f"no hero {folder[len('Hero_'):]!r} with bannable talents")
        banned = []
        for ctl in ctls:
            t = known.get(CONTROLLER_PREFIX + ctl)
            if t is None:
                raise TalentBanError(f"{folder[len('Hero_'):]}/{ctl}: not a bannable talent "
                                     "of that hero (rsmm's talent catalog lists them)")
            banned.append(t)
        for pool, least in MIN_LEFT.items():
            left = [t for t in known.values() if t.pool == pool and t not in banned]
            if len(left) < least:
                hero = next(iter(known.values())).hero
                raise TalentBanError(
                    f"{hero}: banning these leaves {len(left)} talent(s) in the "
                    f"{POOL_NAMES[pool]} pool; it needs at least {least} (an empty pick "
                    "closes at once and blocks every later pick)")
        rel = main_file(folder)
        ef = EntityFile((read or corpus.read)(rel), folder)
        for t in banned:
            set_starts_active(ef, t.controller, on=False)
        out[rel] = ef.to_bytes()
    return out
