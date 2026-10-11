"""The LiveOps version manifest: which magical objects and heroes the game loads.

Moved out of ``cli/apply_mods.py`` (2026-09-26) so the SDK kinds and the item
catalog read it from the engine instead of from a CLI module;
``apply_mods`` re-exports every name for existing callers.
"""

from __future__ import annotations

import json
import shutil
import struct
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from . import cipher
from .paths import BACKUP_SUFFIX, COOKING_REL

if TYPE_CHECKING:
    from rsmm.cli.apply_mods import Mod


# --- magical-object catalog (LiveOps version manifest) -------------------
#
# A new magical-object entity is only LOADED + SPAWNED into the in-game pool
# (so it drops and shows in the compendium) if it is referenced by the active
# LiveOps version manifest. UsedRscList.ot only makes the file loadable-by-path;
# the manifest is what triggers the load. Two install files must list it:
#   * LiveOps5.versiondef.ot.rsionDefinition.gen — a vector<TResourcePtr> of
#     magical-object refs (u32 count, then count x <lstr type><lstr path>).
#   * LiveOps5.versiondef.UsedRscCache.ot — plain text, one line per resource
#     ``<category>|<path>|<class>`` so the manifest's ref resolves at load.
# Verified in-game 2026-06-02 (pool count 104 -> 105, item visible).
VERSIONDEF_GEN_LEAF = "LiveOps5.versiondef.ot.rsionDefinition.gen"
VERSIONDEF_CACHE_LEAF = "LiveOps5.versiondef.UsedRscCache.ot"


def _locate_cooked_by_leaf(game_dir: Path, decoded_leaf: str) -> Path | None:
    """Find the real loose ``_Cooking`` file whose decoded *filename* equals
    ``decoded_leaf``. Matches on the decoded leaf rather than re-encoding the
    path: ``cipher.encode`` is ~98% accurate but four letters are genuinely
    ambiguous (``v``/``I``/``Y`` and the ``\\``-collapse), so for an *existing*
    file we decode-and-compare to be exact. (For a *new* asset with no shipped
    file, ``synthesize_encoded`` must rely on ``cipher.encode``.) Skips
    backups."""
    cooking = game_dir / COOKING_REL
    if not cooking.is_dir():
        return None
    for p in cooking.rglob("*"):
        if not p.is_file() or p.name.endswith(BACKUP_SUFFIX):
            continue
        try:
            if cipher.decode(p.name) == decoded_leaf:
                return p
        except (ValueError, KeyError):
            continue
    return None


def _mo_versiondef_path(decoded: str) -> str | None:
    """Map a magical-object entity's decoded cooked path to its versiondef
    reference form, or None if it isn't a magical-object entity.

    ``EntitySettings/Objects/Magical_Objects/<R>/<id>.entity.ot.EntitySettingsResource.gen``
    -> ``Objects\\Magical_Objects\\<R>\\<id>.entity.ot``
    """
    d = decoded.replace("/", "\\")
    if "Magical_Objects\\" not in d or ".entity.ot.EntitySettingsResource.gen" not in d:
        return None
    d = d.split("EntitySettings\\", 1)[-1]                 # drop leading EntitySettings\
    return d[: d.index(".entity.ot") + len(".entity.ot")]  # keep ...entity.ot


def _find_mo_vector(b: bytes) -> tuple[int, int, int] | None:
    """Locate the magical-object ``vector<TResourcePtr>`` in a versiondef .gen.

    Returns ``(count_off, vec_end, count)``: ``count_off`` is the u32 count
    field, entries (``<lstr type><lstr path>`` pairs) run to ``vec_end``. The
    vector is identified by structure (a sizable run whose every entry path
    contains ``Magical_Objects``), so it survives offset shifts across builds.
    """
    N = len(b)

    def rd(o: int):
        if o + 4 > N:
            return None
        ln = struct.unpack_from("<I", b, o)[0]
        if ln <= 0 or ln > 300 or o + 4 + ln > N:
            return None
        s = b[o + 4 : o + 4 + ln]
        if not all(32 <= c < 127 or c == 92 for c in s):
            return None
        return s, o + 4 + ln

    for co in range(N - 4):
        cnt = struct.unpack_from("<I", b, co)[0]
        if not (20 <= cnt <= 2000):
            continue
        o = co + 4
        ok = all_mo = True
        for _ in range(cnt):
            a = rd(o)
            if not a:
                ok = False
                break
            _t, o = a
            a = rd(o)
            if not a:
                ok = False
                break
            p, o = a
            if b"Magical_Objects" not in p:
                all_mo = False
                break
        if ok and all_mo:
            return co, o, cnt
    return None


def _hero_versiondef_path(decoded: str) -> str | None:
    """``Definitions/Heroes/<id>.herodef.ot.DtHeroDefinition.gen`` ->
    ``Heroes\\<id>.herodef.ot``, or None for anything else."""
    d = decoded.replace("\\", "/")
    pre, suf = "Definitions/Heroes/", ".herodef.ot.DtHeroDefinition.gen"
    if not (d.startswith(pre) and d.endswith(suf)) or "/" in d[len(pre):]:
        return None
    return "Heroes\\" + d[len(pre):-len(suf)] + ".herodef.ot"


def _mo_icon_cache_ref(decoded: str) -> str | None:
    """``Ui/Objects/UI_Object_<id>.png.Texture.dxt`` -> ``Objects\\UI_Object_<id>.png``
    (the form the resource cache and the item entity both use), or None.

    The versiondef cache is the ONLY one of the 599 shipped caches that lists
    an item icon (all 94 of them), so a mod item's own icon has no other
    preloader: without this line it is registered but never preloaded.
    """
    d = decoded.replace("\\", "/")
    pre, suf = "Ui/Objects/", ".png.Texture.dxt"
    if not (d.startswith(pre) and d.endswith(suf)) or "/" in d[len(pre):]:
        return None
    return "Objects\\" + d[len(pre):-len(".Texture.dxt")]


def _find_hero_vector(b: bytes) -> tuple[int, int, int] | None:
    """Locate the versiondef's hero ``vector<TResourcePtr>`` (12 shipped).

    The hero roster screen lists every REGISTERED herodef, and a herodef is
    only loaded through this vector: a clone registered in UsedRscList alone
    loaded nothing (2026-09-24, 12 defs live). Same structural search as
    :func:`_find_mo_vector` — every entry's path ends in ``.herodef.ot``.
    """
    N = len(b)
    needle = b".herodef.ot"
    first = b.find(needle)
    while first >= 0:
        # Walk back to the u32 count in front of the first ("Definitions", path)
        # pair: path lstr starts len(path)+4 before its end; type lstr before it.
        for co in range(max(0, first - 400), first):
            cnt = struct.unpack_from("<I", b, co)[0] if co + 4 <= N else 0
            if not 1 <= cnt <= 256:
                continue
            o, ok = co + 4, True
            for _ in range(cnt):
                for want_hero in (False, True):
                    if o + 4 > N:
                        ok = False
                        break
                    ln = struct.unpack_from("<I", b, o)[0]
                    if not 0 < ln <= 300 or o + 4 + ln > N:
                        ok = False
                        break
                    s = b[o + 4:o + 4 + ln]
                    if want_hero and not s.endswith(needle):
                        ok = False
                        break
                    o += 4 + ln
                if not ok:
                    break
            if ok:
                return co, o, cnt
        first = b.find(needle, first + 1)
    return None


def _patch_versiondef_heroes(pristine: bytes, paths: list[str]) -> bytes | None:
    """Append each herodef in ``paths`` to the hero vector. None if not found."""
    loc = _find_hero_vector(pristine)
    if loc is None:
        return None
    co, vec_end, cnt = loc
    have = {e[2] for e in _mo_vector_entries(pristine, co, cnt)}
    add = b""
    for path in paths:
        if path in have:
            continue
        pb = path.encode("latin1")
        add += struct.pack("<I", len(b"Definitions")) + b"Definitions"
        add += struct.pack("<I", len(pb)) + pb
    if not add:
        return pristine
    added = sum(1 for p in paths if p not in have)
    return (pristine[:co] + struct.pack("<I", cnt + added)
            + pristine[co + 4:vec_end] + add + pristine[vec_end:])


def _mo_vector_entries(b: bytes, co: int, cnt: int) -> list[tuple[int, int, str]]:
    """Split the MO vector into ``(start, end, path)`` per entry.

    Offsets are absolute and span the whole ``<lstr type><lstr path>`` pair, so
    an entry can be dropped by simply not copying its slice.
    """
    def rd(o: int) -> tuple[str, int]:
        ln = struct.unpack_from("<I", b, o)[0]
        return b[o + 4 : o + 4 + ln].decode("latin1"), o + 4 + ln

    out: list[tuple[int, int, str]] = []
    o = co + 4
    for _ in range(cnt):
        start = o
        _type, o = rd(o)          # "EntitySettings"
        path, o = rd(o)
        out.append((start, o, path))
    return out


def _mo_entry_stem(path: str) -> str:
    """``Objects\\Magical_Objects\\Common\\Armor_Per_Object.entity.ot`` ->
    ``Armor_Per_Object``."""
    leaf = path.replace("/", "\\").rsplit("\\", 1)[-1]
    return leaf.split(".entity.ot", 1)[0]


def _patch_versiondef_gen(pristine: bytes, paths: list[str],
                          bans: set[str] | None = None) -> bytes | None:
    """Return ``pristine`` with the MO vector rebuilt: every ``bans`` entry
    dropped, then each ``paths`` entry appended, count set to what survived.
    None if the vector can't be located.

    Both edits go through one rebuild rather than an append plus a separate
    delete, so the count field can never disagree with the entries actually
    present — a mismatch the engine reads as a truncated or over-long vector.
    """
    loc = _find_mo_vector(pristine)
    if loc is None:
        return None
    co, vec_end, cnt = loc
    entries = _mo_vector_entries(pristine, co, cnt)
    banned = {b.lower() for b in (bans or ())}
    kept = [e for e in entries if _mo_entry_stem(e[2]).lower() not in banned]
    have = {e[2] for e in kept}

    add = b""
    added = 0
    for path in paths:
        if path in have:
            continue  # already referenced
        pb = path.encode("latin1")
        add += struct.pack("<I", len(b"EntitySettings")) + b"EntitySettings"
        add += struct.pack("<I", len(pb)) + pb
        added += 1
    if added == 0 and len(kept) == len(entries):
        return pristine
    body = b"".join(pristine[s:e] for s, e, _ in kept)
    return (pristine[:co] + struct.pack("<I", len(kept) + added)
            + body + add + pristine[vec_end:])


def _mo_entry_rarity(path: str) -> str:
    """``Objects\\Magical_Objects\\Common\\X.entity.ot`` -> ``Common``."""
    parts = path.replace("/", "\\").split("\\")
    return parts[-2] if len(parts) >= 2 else ""


def _clamp_bans(pristine: bytes, bans: set[str]) -> set[str]:
    """Refuse a ban set that would empty any rarity in the catalog.

    The engine picks an offer with `rand() % candidate_count`, so a pool that
    reaches zero is not an empty shop — it is an INT_DIVIDE_BY_ZERO that kills
    the process (observed 2026-08-28: 103 of 104 items banned, crash at
    0x1405183dd on opening the shop).

    Rarity is the grouping the catalog itself is organised by, and the small
    ones are small — Common and Rare ship 10 items each — so a single global
    floor would happily allow wiping one out. This does NOT prove a ban is
    safe: the per-slot candidate sets are not mapped, and a slot that only ever
    offers one specific item would still break. It rules out the whole-pool
    case, which is the one that has actually been seen.

    The set is refused whole rather than partially applied: choosing which of
    the user's picks to honour would be inventing intent, and a loud no-op they
    can act on beats a half-applied edit they cannot see.
    """
    if not bans:
        return bans
    loc = _find_mo_vector(pristine)
    if loc is None:
        return bans
    co, _vec_end, cnt = loc
    entries = _mo_vector_entries(pristine, co, cnt)
    lowered = {b.lower() for b in bans}

    total: dict[str, int] = {}
    banned: dict[str, int] = {}
    for _s, _e, ref in entries:
        rarity = _mo_entry_rarity(ref) or "?"
        total[rarity] = total.get(rarity, 0) + 1
        if _mo_entry_stem(ref).lower() in lowered:
            banned[rarity] = banned.get(rarity, 0) + 1

    emptied = sorted(r for r, n in total.items() if banned.get(r, 0) >= n)
    if not emptied:
        return bans
    detail = ", ".join(f"{r} ({total[r]})" for r in emptied)
    print(f"  [warn] ban: refusing the whole ban list — it would leave no items "
          f"at all in: {detail}. The game picks offers with a modulo over the "
          f"candidate count, so an empty pool is a divide-by-zero crash, not an "
          f"empty shop. Nothing banned.", file=sys.stderr)
    return set()


def _warn_unmatched_bans(pristine: bytes, bans: set[str]) -> None:
    """Report ban ids that match no entry in the install's own MO vector.

    Banning a name no item has is a well-formed no-op that emits, installs and
    reports success, and only shows up as "the banned item still dropped" a
    playtest later — so it is called out loudly here even though it cannot fail
    the apply.
    """
    if not bans:
        return
    loc = _find_mo_vector(pristine)
    if loc is None:
        return
    co, _vec_end, cnt = loc
    have = {_mo_entry_stem(e[2]).lower()
            for e in _mo_vector_entries(pristine, co, cnt)}
    missing = sorted(b for b in bans if b.lower() not in have)
    if missing:
        print(f"  [warn] ban: no item named {', '.join(missing)} in the "
              f"LiveOps manifest ({cnt} items); nothing banned for those",
              file=sys.stderr)


def collect_item_bans(mods: list[Mod]) -> set[str]:
    """Union the item ids every enabled mod stages under ``_pending_bans/``.

    Unioned rather than last-one-wins for the same reason mod content merges
    elsewhere do: two mods each banning a different item must yield both bans,
    and a ban is idempotent, so a union can never produce a worse result than
    either mod alone.
    """
    out: set[str] = set()
    for m in mods:
        if not m.enabled:
            continue
        d = m.assets_dir / "_pending_bans"
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.json")):
            try:
                doc = json.loads(f.read_text(encoding="utf-8"))
            except (OSError, ValueError) as e:
                print(f"  [warn] {m.id}: unreadable ban file {f.name}: {e}",
                      file=sys.stderr)
                continue
            out.update(str(x) for x in (doc.get("items") or []))
    return out


def sync_versiondef(game_dir: Path, registrations: dict[str, str],
                    dry_run: bool, bans: set[str] | None = None) -> int:
    """Ensure every new magical-object entity in ``registrations`` is listed in
    the active LiveOps version manifest (.gen vector) AND its resource cache,
    so the engine loads + spawns it, and that every id in ``bans`` is NOT — so
    the engine never pools it and no draw can offer it. Both files are backed
    up once and rebuilt from the pristine backup each apply (idempotent; clean
    drop on removal). Returns the number of files changed.

    A ban touches only the .gen vector, never the resource cache: the banned
    entity's file is still on disk and other assets may still reference it, and
    a surplus cache line only wastes a preload while a missing one crashes the
    load (see the ``UsedRscCache`` invariant in CLAUDE.md).
    """
    bans = bans or set()
    mo_paths = sorted(
        {p for d in registrations.values() if (p := _mo_versiondef_path(d))}
    )
    hero_paths = sorted(
        {p for d in registrations.values() if (p := _hero_versiondef_path(d))}
    )
    icon_paths = sorted(
        {p for d in registrations.values() if (p := _mo_icon_cache_ref(d))}
    )
    gen = _locate_cooked_by_leaf(game_dir, VERSIONDEF_GEN_LEAF)
    cache =_locate_cooked_by_leaf(game_dir, VERSIONDEF_CACHE_LEAF)

    changed = 0
    # --- .gen vector ---
    if gen is not None:
        bak = gen.with_name(gen.name + BACKUP_SUFFIX)
        if not mo_paths and not bans and not hero_paths:
            if bak.exists() and not dry_run:
                shutil.copy2(bak, gen)
                bak.unlink()
                changed += 1
                print("  [versiondef] restored pristine manifest")
        else:
            if not bak.exists() and not dry_run:
                shutil.copy2(gen, bak)
            pristine = (bak if bak.exists() else gen).read_bytes()
            _warn_unmatched_bans(pristine, bans)
            bans = _clamp_bans(pristine, bans)
            patched = _patch_versiondef_gen(pristine, mo_paths, bans)
            if patched is not None and hero_paths:
                with_heroes = _patch_versiondef_heroes(patched, hero_paths)
                if with_heroes is None:
                    print("  [warn] could not locate the hero vector in "
                          f"{gen.name}; new heroes won't load", file=sys.stderr)
                else:
                    patched = with_heroes
            if patched is None:
                print("  [warn] could not locate magical-object vector in "
                      f"{gen.name}; new item won't spawn", file=sys.stderr)
            elif patched != gen.read_bytes():
                what = []
                if mo_paths:
                    what.append(f"registering {len(mo_paths)} item(s)")
                if hero_paths:
                    what.append(f"registering {len(hero_paths)} hero(es)")
                if bans:
                    what.append(f"banning {len(bans)} item(s)")
                print(f"  [versiondef] {' + '.join(what)} in LiveOps manifest")
                if not dry_run:
                    gen.write_bytes(patched)
                changed += 1
    elif mo_paths or hero_paths:
        print("  [warn] LiveOps versiondef .gen not found; new magical objects "
              "and heroes won't load", file=sys.stderr)

    # --- UsedRscCache text ---
    if cache is not None:
        bak = cache.with_name(cache.name + BACKUP_SUFFIX)
        lines = [f"EntitySettings|{p}|oCEntitySettingsResource" for p in mo_paths]
        lines += [f"Definitions|{p}|oCDtHeroDefinition" for p in hero_paths]
        lines += [f"Ui|{p}|oCTexture" for p in icon_paths]
        if not lines:
            if bak.exists() and not dry_run:
                shutil.copy2(bak, cache)
                bak.unlink()
                changed += 1
        else:
            if not bak.exists() and not dry_run:
                shutil.copy2(cache, bak)
            pristine = (bak if bak.exists() else cache).read_bytes()
            add = b"".join(
                b"\n" + ln.encode("latin1") for ln in lines
                if ln.encode("latin1") not in pristine
            )
            if add:
                body = pristine + add + (b"" if pristine.endswith(b"\n") else b"\n")
                if body != cache.read_bytes():
                    if not dry_run:
                        cache.write_bytes(body)
                    changed += 1
    return changed
