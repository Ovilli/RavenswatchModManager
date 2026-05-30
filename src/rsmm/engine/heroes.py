"""
Hero text registry — abilities + skills (talents) for every hero.

Each hero ships a `Hero_<Name>_Common~GAM.xls.LocalText.gen` text bank
with structured keys:

    Hero_Name                              hero label
    Hero_Desc                              hero description
    Ability_<Slot>_Name / _Desc            one of Trait, Attack, Power,
                                           Special, Defense, Ultimate_1,
                                           Ultimate_2
    Skill_<KindAndName>_Name / _Desc       talents (Passive_, Dash_,
                                           Trait_, Attack_, Special_,
                                           Defense_, Ultimate_, Power_,
                                           Misc_, ...)

This module enumerates each hero, parses both the base (keys) file and
the EN value file so the GUI can show current text + write changes.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from .paths import DATA_DIR

_TEXT_DIR = DATA_DIR / "uncooked" / "Text"
_HERO_RE = re.compile(r"^Hero_(.+?)_Common~GAM\.xls\.LocalText\.gen$")
_SKIN_KEY_RE = re.compile(r"^(?:Ability_|Skill_)")


@dataclass
class HeroEntry:
    key:    str            # raw text-bank key
    label:  str            # human label derived from key
    value:  str            # current EN value (empty if missing)
    kind:   str            # "ability" | "skill" | "meta"


@dataclass
class Hero:
    name:        str                  # e.g. "Romeo"
    bank:        str                  # short bank name e.g. "Hero_Romeo_Common"
    abilities:   list[HeroEntry] = field(default_factory=list)
    skills:      list[HeroEntry] = field(default_factory=list)
    meta:        list[HeroEntry] = field(default_factory=list)


def _human_label(key: str) -> str:
    """`Skill_Passive_Attack_Block_Name` -> 'Passive Attack Block'."""
    s = key
    for prefix in ("Ability_", "Skill_"):
        if s.startswith(prefix):
            s = s[len(prefix):]
            break
    for suffix in ("_Name", "_Desc"):
        if s.endswith(suffix):
            s = s[: -len(suffix)]
            break
    return s.replace("_", " ")


def _classify(key: str) -> str:
    if key.startswith("Ability_"):
        return "ability"
    if key.startswith("Skill_"):
        return "skill"
    return "meta"


def _pair_keys(keys: list[str]) -> list[tuple[str, str | None]]:
    """Group `_Name` + `_Desc` keys into pairs in source order. Solo
    keys (no matching pair) pass through with the other side = None.
    """
    seen: set[str] = set()
    out: list[tuple[str, str | None]] = []
    for k in keys:
        if k in seen:
            continue
        if k.endswith("_Name"):
            base = k[:-5]
            desc = base + "_Desc"
            seen.add(k)
            seen.add(desc)
            out.append((k, desc if desc in keys else None))
        elif k.endswith("_Desc"):
            base = k[:-5]
            name = base + "_Name"
            if name in keys:
                # paired in an earlier iteration; skip
                seen.add(k)
                seen.add(name)
                continue
            seen.add(k)
            out.append((k, None))
        else:
            seen.add(k)
            out.append((k, None))
    return out


def _parse(bank_base: Path, lang_path: Path) -> tuple[list[str], list[str]]:
    """Return (keys, values_en). Missing files -> empty lists."""
    try:
        from rsmm.engine.text_patches import parse_text_file
    except Exception:
        return [], []
    keys = parse_text_file(bank_base).entries if bank_base.is_file() else []
    vals = parse_text_file(lang_path).entries if lang_path.is_file() else []
    return keys, vals


@lru_cache(maxsize=1)
def registry() -> dict[str, Hero]:
    """hero_name -> Hero record. Empty if data/uncooked/Text missing."""
    out: dict[str, Hero] = {}
    if not _TEXT_DIR.is_dir():
        return out

    for f in sorted(_TEXT_DIR.iterdir()):
        m = _HERO_RE.match(f.name)
        if not m:
            continue
        name = m.group(1)
        # The cooked install uses a `.GgzyMU` (=EN) lang suffix; uncooked
        # mirror may only have the base file. Front-end shows what we
        # have; missing EN values surface as empty strings (placeholders).
        en_path = f.with_name(f.name + ".GgzyMU")
        keys, vals = _parse(f, en_path)
        if not keys:
            continue
        hero = Hero(name=name, bank=f.name.split("~", 1)[0])

        # Walk in source order; pair name+desc visually but expose every
        # key the GUI might want to edit.
        for k in keys:
            i = keys.index(k)
            val = vals[i] if i < len(vals) else ""
            entry = HeroEntry(
                key=k, label=_human_label(k), value=val, kind=_classify(k),
            )
            if entry.kind == "ability":
                hero.abilities.append(entry)
            elif entry.kind == "skill":
                hero.skills.append(entry)
            else:
                hero.meta.append(entry)
        out[name] = hero
    return out


def list_names() -> list[str]:
    return sorted(registry().keys())


def get(name: str) -> Hero | None:
    return registry().get(name)


def to_jsonable() -> list[dict]:
    out = []
    for h in sorted(registry().values(), key=lambda x: x.name):
        out.append({
            "name": h.name,
            "bank": h.bank,
            "abilities": [{"key": e.key, "label": e.label, "value": e.value}
                          for e in h.abilities],
            "skills":    [{"key": e.key, "label": e.label, "value": e.value}
                          for e in h.skills],
            "meta":      [{"key": e.key, "label": e.label, "value": e.value}
                          for e in h.meta],
        })
    return out
