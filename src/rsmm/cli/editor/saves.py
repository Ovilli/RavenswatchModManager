"""The Save tab: what a profile save holds, and the parts of it that can change.

Reads ``<game>/_Save/Profile_N.ob`` through ``engine.profile_data`` (every
record decoded with the engine's own layouts) and shows it by kind: items,
heroes, talents, outfits, story pages, achievements, melodies, challenges and
the player record, each named from the install's own definitions. What can be
changed is what the game itself writes: an item's granted/reset state, a lock's
unlocked/locked state, a hero's level and a talent's tier, each within the
range the game's loader accepts. Every other field is shown and kept as it is;
a suspended run is kept byte for byte.

Writing is the one place rsmm touches a save, so it is fenced: the game must
not be running (it keeps the profile in memory and would write its own copy
back over the edit), the file is re-read and re-decoded at write time and each
change must name the record it was made on (object id AND GUID), and BOTH
``Profile_N.ob`` and ``Profile_N_Temp.ob`` are first copied to a timestamped
folder under rsmm's own data directory. The backups live there rather than in
``_Save`` because Steam Cloud syncs that folder, and because the game folder
(and ``_Save`` with it) goes away when the game is reinstalled. A backup can be
put back from the same tab, and putting one back backs up first.
"""

from __future__ import annotations

import re
import shutil
import time
from pathlib import Path

from rsmm.cli.editor.app import Fail, Request
from rsmm.engine import profile_data as PD
from rsmm.engine import savefile as SF

MOUNT = "save"
PAGE = "save.html"

_PROFILE = re.compile(r"^Profile_\d+\.ob$")
_BACKUP = re.compile(r"^\d{8}-\d{6}(-\d+)?$")
_GUID = re.compile(r"^[0-9a-f]{32}$")

#: Sections, in the order the page shows them: (key, label, record class).
SECTIONS = [
    ("items", "Items", "oCDtMagicalObjectProfileData"),
    ("heroes", "Heroes", "oCDtHeroProfileData"),
    ("talents", "Talents", "SkillProfileData"),
    ("skins", "Outfits", "SkinProfileData"),
    ("story", "Story", "StoryProfileData"),
    ("achievements", "Achievements", "AchievementProfileData"),
    ("melodies", "Melodies", "MelodyProfileData"),
    ("challenges", "Challenges", "ChallengeProfileData"),
]
#: Shown, never written: fields whose meaning is not decoded.
_READ_ONLY = {
    "oCDtHeroProfileData": ("count30", "count32", "count34", "count36", "rank38", "flag108",
                            "value3c", "enum40"),
    "MelodyProfileData": ("flag48", "flag49", "value4c"),
    "ChallengeProfileData": ("value30",),
}


def _game() -> Path:
    from rsmm.cli.apply_mods import find_game_dir
    game = find_game_dir()
    if game is None:
        raise Fail(404, "Ravenswatch was not found, so there is no save to read.")
    return Path(game)


def _save_dir() -> Path:
    d = _game() / "_Save"
    if not d.is_dir():
        raise Fail(404, f"No _Save folder in {d.parent}: start the game once to make a profile.")
    return d


def _backup_root() -> Path:
    from rsmm.engine.paths import user_data_dir
    return user_data_dir() / "save_backups"


def _profile(req: Request) -> Path:
    name = req.arg("profile") or str(req.body.get("profile", ""))
    if not _PROFILE.match(name):
        raise Fail(400, "no such profile")
    p = _save_dir() / name
    if not p.is_file():
        raise Fail(404, f"{name} is not in {p.parent}")
    return p


def _running() -> bool:
    from rsmm.engine.game_proc import is_game_running
    try:
        return is_game_running()
    except OSError:
        return False


def _not_running() -> None:
    if _running():
        raise Fail(409, "Ravenswatch is running. Quit the game first: it keeps your profile in "
                        "memory and would save its own copy over this one.")


def _decode(p: Path) -> PD.Profile:
    try:
        return PD.parse(SF.load(p))
    except SF.SaveFormatError as e:
        raise Fail(422, f"{p.name} can't be read safely: {e}") from e


def _names(prof: PD.Profile) -> dict[str, dict[str, str]]:
    return PD.name_index({n.get("guid"): n.cls for n in prof.objects if "guid" in n.fields})


def _profiles(req: Request) -> dict:
    d = _save_dir()
    rows = []
    for p in SF.find_saves(d.parent):
        if not _PROFILE.match(p.name):
            continue                               # the _Temp copies
        st = p.stat()
        row = {"name": p.name, "size": st.st_size, "modified": int(st.st_mtime)}
        try:
            s = SF.load(p)
            row["crcOk"] = s.crc_ok
            PD.parse(s)
        except SF.SaveFormatError as e:
            row["error"] = str(e)
        rows.append(row)
    return {"dir": str(d), "profiles": rows, "running": _running(), "backups": _backups()}


def _lock(node: PD.Node) -> str:
    return PD.lock_state(node.children["lock"])


def _row(n: PD.Node, oid: int, name: dict, items: dict) -> dict | None:
    guid = n.get("guid")
    row = {"id": oid, "guid": guid, "name": name.get("name") or "?", "group": name.get("group", "")}
    if n.cls == "oCDtMagicalObjectProfileData":
        meta = items.get(name.get("id", ""))
        if meta is None:
            return None                            # a retired item: kept, never offered
        raw = [n.get(k) for k in ("f60", "f61", "f62", "f64", "f68")]
        row.update(name=meta["name"], group=meta["rarity"], icon=meta.get("icon"),
                   item=PD.item_state(n), raw=raw)
    if "lock" in n.children:
        row["lock"] = _lock(n)
        row["new"] = bool(n.children["lock"].get("new"))
    if n.cls == "oCDtHeroProfileData":
        row["level"] = round(n.get("level"), 3)
        row["group"] = ""                          # the hero IS the row
    if n.cls == "SkillProfileData":
        row["tier"] = n.get("tier")
    ro = _READ_ONLY.get(n.cls)
    if ro:
        row["info"] = {k: n.get(k) for k in ro}
    return row


def _read(req: Request) -> dict:
    p = _profile(req)
    prof = _decode(p)
    names = _names(prof)
    from rsmm.cli.editor.content import items as catalog
    items = {i["id"]: i for i in catalog()}
    sections, retired = [], 0
    for key, label, cls in SECTIONS:
        rows = []
        for oid, n in enumerate(prof.objects):
            if n.cls != cls:
                continue
            row = _row(n, oid, names.get(n.get("guid"), {}), items)
            if row is None:
                retired += 1
                continue
            rows.append(row)
        rows.sort(key=lambda r: (r["group"], r["name"]))
        sections.append({"key": key, "label": label, "rows": rows})
    player = {k: f.value for k, f in prof.player.fields.items()}
    return {"profile": p.name, "crcOk": prof.save.crc_ok, "running": _running(),
            "sections": sections, "retired": retired, "player": player,
            "run": prof.run.end - prof.run.start,
            "ranges": {"level": PD.LEVEL_RANGE, "tier": PD.TIER_RANGE}}


#: field -> (record class it applies to, setter)
def _apply(save: SF.Save, n: PD.Node, field: str, value) -> None:
    if field == "item":
        if value not in SF.ITEM_STATES:
            raise ValueError("unknown item state")
        PD.set_item_state(save, n, value)
    elif field == "lock":
        if "lock" not in n.children or value not in PD.LOCK_STATES:
            raise ValueError("unknown lock state")
        PD.set_lock(save, n.children["lock"], value)
    elif field == "level":
        PD.set_hero_level(save, n, float(value))
    elif field == "tier":
        if not isinstance(value, int) or isinstance(value, bool):
            raise ValueError("a talent tier is a whole number")
        PD.set_talent_tier(save, n, value)
    else:
        raise ValueError(f"{field} can't be changed")


def _write(req: Request) -> dict:
    _not_running()
    p = _profile(req)
    changes = req.body.get("changes")
    if not isinstance(changes, list) or not changes:
        raise ValueError("nothing to change")
    if len(changes) > 20000:
        raise ValueError("too many changes in one write")
    prof = _decode(p)                              # what is on disk NOW, not what the page read
    if not prof.save.crc_ok:
        raise ValueError(f"{p.name} fails its own checksum; not editing it")
    for c in changes:
        if not isinstance(c, dict):
            raise ValueError("bad change")
        oid, guid = c.get("id"), str(c.get("guid", ""))
        if not isinstance(oid, int) or not 0 <= oid < len(prof.objects) or not _GUID.match(guid):
            raise ValueError("a change names no record")
        n = prof.objects[oid]
        if n.fields.get("guid") is None or n.get("guid") != guid:
            raise ValueError(f"{p.name} changed since the page read it; reload the page")
        _apply(prof.save, n, str(c.get("field", "")), c.get("value"))
    backup = _backup(p.parent, p.name, f"before the Save tab changed {len(changes)} value(s)")
    SF.resign(prof.save)
    PD.parse(prof.save)                            # the edited file still decodes end to end
    data = bytes(prof.save.data)
    # The game writes Profile_N_Temp.ob and moves it over Profile_N.ob; keep the
    # pair identical, as the game leaves it.
    p.write_bytes(data)
    temp = p.with_name(p.name[:-len(".ob")] + "_Temp.ob")
    if temp.is_file():
        temp.write_bytes(data)
    return {"written": p.name, "changed": len(changes), "backup": backup, "backups": _backups()}


def _backup(save_dir: Path, name: str, why: str) -> str:
    """Copy Profile_N.ob and its _Temp twin into a new timestamped folder."""
    root = _backup_root()
    stamp = time.strftime("%Y%m%d-%H%M%S")
    dest, n = root / stamp, 1
    while dest.exists():
        n += 1
        dest = root / f"{stamp}-{n}"
    dest.mkdir(parents=True)
    stem = name[:-len(".ob")]
    for f in (name, stem + "_Temp.ob"):
        if (save_dir / f).is_file():
            shutil.copy2(save_dir / f, dest / f)
    (dest / "why.txt").write_text(why + "\n", encoding="utf-8")
    return dest.name


def _backups() -> list[dict]:
    root = _backup_root()
    if not root.is_dir():
        return []
    out = []
    for d in sorted(root.iterdir(), reverse=True):
        if d.is_dir() and _BACKUP.match(d.name):
            note = d / "why.txt"
            why = note.read_text(encoding="utf-8").strip() if note.is_file() else ""
            files = sorted(f.name for f in d.glob("Profile_*.ob"))
            out.append({"name": d.name, "files": files, "why": why})
    return out


def _restore(req: Request) -> dict:
    _not_running()
    name = str(req.body.get("backup", ""))
    if not _BACKUP.match(name) or not (_backup_root() / name).is_dir():
        raise Fail(404, "no such backup")
    src = _backup_root() / name
    files = sorted(src.glob("Profile_*.ob"))
    if not files:
        raise ValueError("that backup holds no profile")
    d = _save_dir()
    mains = {f.name for f in files if _PROFILE.match(f.name)}
    for f in files:                                # never put back a file that does not load
        SF.load(f)
    undo = [_backup(d, m, f"before putting back backup {name}") for m in mains]
    for f in files:
        shutil.copy2(f, d / f.name)
    return {"restored": name, "undo": undo, "backups": _backups()}


def _icon(req: Request):
    from rsmm.cli.editor.content import _icon as icon
    return icon(req)


ROUTES = {
    ("GET", "/api/profiles"): _profiles,
    ("GET", "/api/profile"): _read,
    ("GET", "/api/icon"): _icon,
    ("POST", "/api/write"): _write,
    ("POST", "/api/restore"): _restore,
}
