"""Option providers for `multiselect` config fields.

A mod that wants the player to choose from a list the GAME defines — every
magical object, say — cannot spell those options out in its manifest: it does
not know them, they carry art, and they change when the game is patched. So the
schema names a provider and the CLI fills the options in.

The allowlist is the security boundary. A mod supplies a NAME, never a path, a
URL or a command. The desktop webview can spawn the CLI, so anything a mod could
inject here would be arbitrary code execution on the player's machine — the same
reason overlay shape is data and never markup.

An option is a flat record the client renders generically:

    {"id", "label", "group", "icon", "description", "attrs"}

``attrs`` is an optional table of scalar (or list-of-text) attributes an
`item-grid` field can filter and edit on — see `rsmm.sdk.config_grid`.

``icon`` is an inline ``data:image/png;base64,`` URL or empty. Never a path and
never a remote URL, so the client is never made to fetch on a mod's behalf.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any

_log = logging.getLogger(__name__)

__all__ = ["PROVIDERS", "provide", "split_source", "ICON_PREFIX", "MAX_ICON_CHARS"]

ICON_PREFIX = "data:image/png;base64,"
#: A 64px PNG data URL runs ~6 KB. The cap is generous for one and small enough
#: that a provider cannot wedge the client with megabytes of base64.
MAX_ICON_CHARS = 64 * 1024
#: Providers may return large lists (the item catalog is 104), but not unbounded
#: ones — the whole set is rendered at once.
MAX_OPTIONS = 512


def _item_catalog() -> list[dict[str, Any]]:
    """Every magical object the install's catalog can offer.

    The catalog, not the shipped asset corpus: the corpus carries ~20 entities
    the game never offers (``*_Model`` templates, unreleased items), and an
    option nothing can act on is a trap. This is also exactly the set an item
    ban can remove, so the picker cannot show a choice that would not apply.
    """
    import base64

    from rsmm.cli import apply_mods as A
    from rsmm.engine import item_catalog

    game_dir = A.find_game_dir()
    if game_dir is None:
        return []
    out: list[dict[str, Any]] = []
    for it in item_catalog.catalog(game_dir)[:MAX_OPTIONS]:
        png = item_catalog.icon_png(game_dir, it)
        out.append({
            "id": it.id,
            "label": it.name or it.id,
            "group": it.rarity,
            "icon": (ICON_PREFIX + base64.b64encode(png).decode()) if png else "",
            "description": it.description or "",
        })
    return out


def _talent_catalog() -> list[dict[str, Any]]:
    """Every talent a talent ban can keep out of the offers, grouped by hero.

    The bannable set (``engine.talent_bans.catalog``): shipped talents in the
    starting pick and the level-up pool, named, and dealt today. Not ultimates,
    their upgrades or the talents the game cut, so the picker cannot offer a
    choice the ban would refuse. Ids are ``"<Hero>/<controller>"``, the ban's
    own spelling.
    """
    from rsmm.engine import talent_bans

    out: list[dict[str, Any]] = []
    for t in talent_bans.catalog()[:MAX_OPTIONS]:
        where = "starting pick" if t.pool == 0 else "level-up"
        out.append({
            "id": t.id,
            "label": t.name,
            "group": t.hero,
            "icon": "",
            "description": f"{_plain(t.description)} ({where})".strip(),
            "attrs": {"hero": t.hero, "pool": where},
        })
    return out


#: The game's card markup: #...@ highlights, &...~ scaling values, {N} slots.
def _plain(text: str) -> str:
    import re
    return re.sub(r"\s+", " ", re.sub(r"[#@&~]", "", text or "")).strip()


def _enemy_roster() -> list[dict[str, Any]]:
    """Every creature a camp selector can roll, grouped by the chapter it
    ships in.

    The spawnable set, not every enemy definition: bosses, summons and quest
    enemies are placed by the script owning their encounter, so casting one
    would emit a definition pointing at a prefab no chapter streams. Same rule
    the `enemy` kind enforces at emit — the picker must not offer a choice that
    would then be refused.

    Ids are prefab stems (`Standard_Reef_Crab`), which are unique across the
    50 and are one of the three spellings `rsmm.sdk.kinds.enemies` accepts, so
    a stored selection reads the same by hand or through the panel. No icons:
    enemy art lives in the entity's material chain rather than in a UI atlas
    the way an item's does.

    Read through `enemy_pools`, which answers from the uncooked mirror on an
    authoring checkout and from the game install's own cooked tree everywhere
    else — so the picker is populated on a plain install, which is the only
    machine that matters for a downloaded mod. Empty only when rsmm cannot
    find the game at all.
    """
    from rsmm.engine import enemy_pools as EP

    by_pool = EP.pool_of_entity()
    out: list[dict[str, Any]] = []
    for ent in EP.spawnable_entities()[:MAX_OPTIONS]:
        stem = ent.replace("/", "\\").split("\\")[-1].split(".", 1)[0]
        out.append({
            "id": stem,
            "label": stem.replace("_", " "),
            "group": (by_pool.get(ent.lower()) or "").replace("_", " "),
            "icon": "",
            "description": ent,
        })
    return out


def _shop_items() -> list[dict[str, Any]]:
    """Every item the Sandman's offer generators can sell, with its ``role``,
    ``price``, ``priceEditable`` and ``defaultIn`` (the generators offering it
    unmodded). Data only — how a grid shows these is the mod's schema's call."""
    from rsmm.cli import apply_mods as A
    from rsmm.engine import shop_catalog

    return shop_catalog.options(A.find_game_dir())


def _fmod_pretty(seg: str) -> str:
    return seg.replace("_", " ").strip() or seg


def _fmod_event_label(name: str) -> str:
    """`HRh_PrimaryFinisher_Anim` -> `Primary Finisher Anim`.

    Event names lead with a hero code (`HRh_`, `HSW_`, `HK_`, ...): an `H` and
    up to three more letters. It says nothing the hero's own list does not, so
    it is dropped; CamelCase is split so the rest reads as words.
    """
    import re

    parts = name.split("_")
    if len(parts) > 1 and re.fullmatch(r"H[A-Za-z]{1,3}", parts[0]):
        parts = parts[1:]
    words = " ".join(p for p in parts if p)
    words = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", words)
    return words or name


def _fmod_sounds(arg: str | None = None) -> list[dict[str, Any]]:
    """What a player can choose to mute, read from the game's FMOD strings bank.

    Ids are FMOD's own paths, so `R.audio.select` takes a stored selection as
    is. Without an argument (``source = "fmod-sounds"``) the list is coarse:

    * ``all`` — every sound (FMOD's master);
    * every mixer BUS (``bus:/Music``, ``bus:/SFX/GUI``, …) — muting a bus
      silences everything routed through it, sub-buses included;
    * every event FOLDER down to three levels (``event:/Heroes/Red``, …) —
      muting one silences every event under it.

    With a folder argument (``source = "fmod-sounds:event:/Heroes/Red"``) it is
    fine-grained: that whole folder, each sub-folder, then EVERY single event
    inside it, grouped by sub-folder. That is how a mod offers one list per
    hero — the full 3,482-event set is too large for one panel (MAX_OPTIONS).

    Read from the install every time, so a game patch that adds sounds shows
    them without an rsmm release. Empty when the game or bank is not found.
    """
    from collections import Counter

    from rsmm.cli import apply_mods as A
    from rsmm.engine import fmod_strings

    game_dir = A.find_game_dir()
    if game_dir is None:
        return []
    all_paths = fmod_strings.paths(game_dir)
    if arg:
        return _fmod_folder(all_paths, arg)

    out: list[dict[str, Any]] = [{
        "id": "all", "label": "Every sound", "group": "Everything",
        "description": "Music, effects, voices, menus and ambience: all of it.",
    }]
    for p in all_paths:
        if not p.startswith("bus:/") or p == "bus:/":
            continue
        segs = p[len("bus:/"):].split("/")
        out.append({
            "id": p,
            "label": " › ".join(_fmod_pretty(x) for x in segs),
            "group": "Mixer: " + _fmod_pretty(segs[0]),
            "description": f"{p}: everything mixed through this bus.",
        })

    events = [p[len("event:/"):].split("/") for p in all_paths if p.startswith("event:/")]
    folders: Counter[tuple[str, ...]] = Counter()
    for segs in events:
        for depth in range(1, min(3, len(segs) - 1) + 1):
            folders[tuple(segs[:depth])] += 1
    for key in sorted(folders):
        path = "event:/" + "/".join(key)
        n = folders[key]
        out.append({
            "id": path,
            "label": " › ".join(_fmod_pretty(x) for x in key),
            "group": "Sounds: " + _fmod_pretty(key[0]),
            "description": f"{path}: {n} sound{'s' if n != 1 else ''}.",
        })
    return out


def _fmod_folder(all_paths: list[str], root: str) -> list[dict[str, Any]]:
    """One event folder in full: itself, its sub-folders, every event."""
    from collections import Counter

    root = root.rstrip("/")
    lo = root.lower() + "/"
    inside = [p for p in all_paths if p.lower().startswith(lo)]
    if not inside:
        return []
    rel = [p[len(lo):].split("/") for p in inside]
    out: list[dict[str, Any]] = [{
        "id": root, "label": "Everything in this list", "group": "Whole folder",
        "description": f"{root}: {len(inside)} sounds.",
    }]
    subs: Counter[tuple[str, ...]] = Counter()
    for segs in rel:
        for depth in range(1, len(segs)):
            subs[tuple(segs[:depth])] += 1
    for key in sorted(subs):
        path = root + "/" + "/".join(key)
        out.append({
            "id": path,
            "label": " › ".join(_fmod_pretty(x) for x in key),
            "group": "Folders",
            "description": f"{path}: {subs[key]} sound{'s' if subs[key] != 1 else ''}.",
        })
    for p, segs in sorted(zip(inside, rel, strict=True),
                          key=lambda t: ("/".join(t[1][:-1]).lower(), t[1][-1].lower())):
        out.append({
            "id": p,
            "label": _fmod_event_label(segs[-1]),
            "group": " › ".join(_fmod_pretty(x) for x in segs[:-1]) or "General",
            "description": p,
        })
    return out


#: name -> builder. The single source of truth for what a schema's `source` may
#: name; `rsmm.sdk.config` validates against these keys.
PROVIDERS: dict[str, Callable[..., list[dict[str, Any]]]] = {
    "item-catalog": _item_catalog,
    "talent-catalog": _talent_catalog,
    "enemy-roster": _enemy_roster,
    "shop-items": _shop_items,
    "fmod-sounds": _fmod_sounds,
}


#: Attribute values an option may carry: short text, numbers, bools, or a short
#: list of text. Anything else is dropped rather than forwarded to the client.
_MAX_ATTRS = 16


def _clean_attrs(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {}
    out: dict[str, Any] = {}
    for k, v in list(raw.items())[:_MAX_ATTRS]:
        key = str(k)[:40]
        if isinstance(v, bool | int | float):
            out[key] = v
        elif isinstance(v, str):
            out[key] = v[:120]
        elif isinstance(v, list) and all(isinstance(x, str) for x in v):
            out[key] = [x[:64] for x in v[:32]]
    return out


def _clean(opt: Any) -> dict[str, Any] | None:
    if not isinstance(opt, dict):
        return None
    oid = str(opt.get("id", "")).strip()
    if not oid:
        return None
    icon = opt.get("icon") or ""
    if (not isinstance(icon, str) or not icon.startswith(ICON_PREFIX)
            or len(icon) > MAX_ICON_CHARS):
        icon = ""
    out = {
        "id": oid,
        "label": str(opt.get("label") or oid)[:120],
        "group": str(opt.get("group") or "")[:40],
        "icon": icon,
        "description": str(opt.get("description") or "")[:400],
    }
    attrs = _clean_attrs(opt.get("attrs"))
    if attrs:
        out["attrs"] = attrs
    return out


#: Providers that take an argument after a colon (``fmod-sounds:event:/Heroes``)
#: and the shape that argument must have. Validated here, not by the provider,
#: so a schema with a bad argument fails at load instead of opening empty.
_ARG_PROVIDERS: dict[str, Callable[[str], bool]] = {
    "fmod-sounds": lambda a: a.startswith("event:/") and len(a) <= 200
    and all(c.isprintable() for c in a),
}


def split_source(name: str) -> tuple[str, str | None]:
    """``"fmod-sounds:event:/Heroes/Red"`` -> ``("fmod-sounds", "event:/Heroes/Red")``.

    Raises ValueError for an unknown provider, or an argument the provider
    does not take / does not accept.
    """
    base, sep, arg = name.partition(":")
    if base not in PROVIDERS:
        raise ValueError(f"unknown provider {base!r}")
    if not sep:
        return base, None
    check = _ARG_PROVIDERS.get(base)
    if check is None:
        raise ValueError(f"{base} takes no argument")
    if not check(arg):
        raise ValueError(f"bad argument {arg!r} for {base}")
    return base, arg


def provide(name: str) -> list[dict[str, Any]]:
    """Options for an allowlisted provider.

    Returns an empty list — never raises — when the provider is unknown or
    cannot read the game: a config panel that opens with no options is a far
    better failure than one that will not open at all.
    """
    try:
        base, arg = split_source(name)
    except ValueError as exc:
        _log.warning("config option provider %r: %s", name, exc)
        return []
    build = PROVIDERS[base]
    try:
        raw = build(arg) if arg is not None else build()
    except Exception as exc:                    # noqa: BLE001 - provider is data-driven
        _log.warning("config option provider %s failed: %s", name, exc)
        return []
    return [c for c in (_clean(o) for o in raw[:MAX_OPTIONS]) if c is not None]
