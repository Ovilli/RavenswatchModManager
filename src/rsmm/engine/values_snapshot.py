"""A backup of one game patch's values, and what a later patch changed.

A game update rebalances numbers in place: an item's modifier, a talent's
value, an ability's timer. Mods are written against the numbers they saw, an
item's ``value_patches`` even record the OLD value they expect, and the
installer keeps no copy of what the previous patch shipped (a game update
replaces the files `.rsmm.bak` was taken from). So before an update lands,
:func:`snapshot` saves two things under ``<user data>/snapshots/<name>/``:

* ``values.json.gz``: every field of every entity (``EntitySettings/``) as
  the editors show it (``rsmm entity-graph`` text: numbers, links, objects),
  plus each magical object's value labels and modifiers by stat name. This
  is what :func:`diff` compares.
* ``cooked.tar.gz``: the pristine cooked bytes of ``EntitySettings/``,
  ``Definitions/`` and ``GlobalValues/``, by decoded path. These are the
  actual backup: a value the readable dump does not decode is still kept.

Everything is read from the INSTALL (pristine ``.rsmm.bak`` first), never
the authoring mirror, because the mirror may be from an older patch than the
one being backed up. Nothing here writes to the game directory.
"""

from __future__ import annotations

import gzip
import io
import json
import re
import tarfile
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path

FORMAT = 1
#: Decoded prefixes whose cooked bytes go into the backup archive.
RAW_PREFIXES = ("EntitySettings/", "Definitions/", "GlobalValues/")
ENTITY_PREFIX = "EntitySettings/"
ENTITY_SUFFIX = ".entity.ot.EntitySettingsResource.gen"
_ITEMS = "EntitySettings/Objects/Magical_Objects/"


class SnapshotError(RuntimeError):
    pass


# --- reading the live patch -------------------------------------------------

def _install_reader() -> tuple[Callable[[str], bytes | None], Callable[[str], list[str]]]:
    """``(read, rels)`` over the install only (pristine copy first)."""
    from . import corpus
    from .asset_map import decoded_to_encoded

    if corpus.cooking_dir() is None:
        raise SnapshotError("no game install found (set RSMM_GAME_DIR)")
    keys = sorted(decoded_to_encoded())

    def read(rel: str) -> bytes | None:
        p = corpus.install_path(rel)
        try:
            return p.read_bytes() if p is not None else None
        except OSError:
            return None

    def rels(prefix: str) -> list[str]:
        return [k for k in keys if k.startswith(prefix)]

    return read, rels


def build_id(game_dir: Path) -> str | None:
    """Steam's build id for the install (``appmanifest_*.acf`` beside it)."""
    steamapps = game_dir.parent.parent
    for acf in sorted(steamapps.glob("appmanifest_*.acf")):
        try:
            text = acf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        if re.search(r'"installdir"\s*"Ravenswatch"', text, re.IGNORECASE):
            m = re.search(r'"buildid"\s*"(\d+)"', text)
            return m.group(1) if m else None
    return None


def entity_values(raw: bytes, name: str = "") -> dict[str, dict[str, str]]:
    """``{component path: {field: text}}`` for one entity file. A name used
    twice gets ``#n`` from its second use on, so every key is stable."""
    from . import entity_fields as EF
    from . import entity_graph as EG

    out: dict[str, dict[str, str]] = {}
    for c in EG.parse(raw, name).components:
        key = c.path or c.name
        n = 2
        while key in out:
            key, n = f"{c.path or c.name}#{n}", n + 1
        fields: dict[str, str] = {}
        for f in EF.fields(c):
            fk, m = f.name, 2
            while fk in fields:
                fk, m = f"{f.name}#{m}", m + 1
            fields[fk] = f.text
        out[key] = fields
    return out


def item_values(raw: bytes) -> dict:
    """A magical object's numbers and modifiers, by the labels ``value_patches``
    takes: the label scanner's, plus every number part and modifier amount
    :func:`~rsmm.engine.magic_item_cook.item_numbers` finds by structure."""
    from . import item_modifier as IM
    from . import magic_item_cook as cook

    values = dict(cook.list_value_fields(raw))
    for v in cook.item_numbers(raw)[0]:
        values.setdefault(v["label"], v["value"])
    return {
        "values": values,
        "modifiers": [{"name": m.name, "stat": m.stat or f"0x{m.key:08x}",
                       "super": bool(m.super_effect)} for m in IM.list_modifiers(raw)],
    }


def collect(read: Callable[[str], bytes | None], rels: Callable[[str], list[str]],
            *, progress: Callable[[int, int], None] | None = None) -> dict:
    """The readable dump: ``{"entities": {rel: ...}, "items": {rel: ...},
    "unreadable": [rel, ...]}``. A file the decoder cannot parse is listed,
    not fatal: its bytes are still in the archive."""
    ents = [r for r in rels(ENTITY_PREFIX) if r.endswith(ENTITY_SUFFIX)]
    out: dict = {"entities": {}, "items": {}, "unreadable": []}
    for i, rel in enumerate(ents, 1):
        raw = read(rel)
        if raw is None:
            continue
        try:
            out["entities"][rel] = entity_values(raw, rel.rsplit("/", 1)[-1])
        except Exception:                       # noqa: BLE001 - one bad file, not the backup
            out["unreadable"].append(rel)
            continue
        if rel.startswith(_ITEMS):
            try:
                out["items"][rel] = item_values(raw)
            except Exception:                   # noqa: BLE001
                pass
        if progress:
            progress(i, len(ents))
    return out


# --- writing and reading snapshots ------------------------------------------

def snapshots_dir() -> Path:
    from .paths import user_data_dir
    return user_data_dir() / "snapshots"


@dataclass
class Snapshot:
    path: Path
    meta: dict
    values: dict = field(default_factory=dict)


def snapshot(name: str | None = None, *, out_dir: Path | None = None,
             progress: Callable[[int, int], None] | None = None) -> Snapshot:
    """Back up the installed patch's values (see the module docstring)."""
    from .paths import default_game_dir, game_fingerprint

    read, rels = _install_reader()
    game = Path(default_game_dir())
    build = build_id(game)
    meta = {"format": FORMAT, "created": time.strftime("%Y-%m-%dT%H:%M:%S"),
            "build_id": build, "fingerprint": game_fingerprint(game)}
    name = name or f"{time.strftime('%Y-%m-%d')}-build{build or 'unknown'}"
    if not re.fullmatch(r"[A-Za-z0-9._-]+", name):
        raise SnapshotError(f"snapshot name {name!r}: letters, digits, . _ - only")
    dest = (out_dir or snapshots_dir()) / name
    if dest.exists():
        raise SnapshotError(f"{dest} already exists; pick another --name")

    values = collect(read, rels, progress=progress)
    tmp = dest.with_name(dest.name + ".partial")
    tmp.mkdir(parents=True, exist_ok=True)
    count = 0
    with tarfile.open(tmp / "cooked.tar.gz", "w:gz") as tar:
        for prefix in RAW_PREFIXES:
            for rel in rels(prefix):
                raw = read(rel)
                if raw is None:
                    continue
                info = tarfile.TarInfo(rel)
                info.size, info.mtime = len(raw), int(time.time())
                tar.addfile(info, io.BytesIO(raw))
                count += 1
    meta["files"] = count
    meta["entities"] = len(values["entities"])
    meta["unreadable"] = len(values["unreadable"])
    with gzip.open(tmp / "values.json.gz", "wt", encoding="utf-8") as fh:
        json.dump({"meta": meta, **values}, fh, separators=(",", ":"), sort_keys=True)
    (tmp / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    tmp.rename(dest)       # a crash part-way leaves `.partial`, never a short snapshot
    return Snapshot(dest, meta, values)


def resolve(ref: str) -> Path:
    """A snapshot by directory path, or by name under :func:`snapshots_dir`."""
    p = Path(ref).expanduser()
    if (p / "values.json.gz").is_file():
        return p
    q = snapshots_dir() / ref
    if (q / "values.json.gz").is_file():
        return q
    raise SnapshotError(f"no snapshot {ref!r} (see `rsmm values list`)")


def load(ref: str) -> Snapshot:
    path = resolve(ref)
    with gzip.open(path / "values.json.gz", "rt", encoding="utf-8") as fh:
        data = json.load(fh)
    meta = data.pop("meta", {})
    if meta.get("format") != FORMAT:
        raise SnapshotError(f"{path}: snapshot format {meta.get('format')}, expected {FORMAT}")
    return Snapshot(path, meta, data)


def live(progress: Callable[[int, int], None] | None = None) -> Snapshot:
    """The installed patch, read now and not written anywhere."""
    from .paths import default_game_dir
    read, rels = _install_reader()
    return Snapshot(Path(default_game_dir()), {"build_id": build_id(Path(default_game_dir()))},
                    collect(read, rels, progress=progress))


def listing() -> list[dict]:
    out = []
    d = snapshots_dir()
    for p in sorted(d.iterdir()) if d.is_dir() else []:
        meta_p = p / "meta.json"
        if meta_p.is_file():
            try:
                out.append({"name": p.name, "path": str(p),
                            **json.loads(meta_p.read_text(encoding="utf-8"))})
            except (OSError, json.JSONDecodeError):
                continue
    return out


def restore_file(ref: str, rel: str) -> bytes:
    """One file's cooked bytes as the snapshot's patch shipped them."""
    with tarfile.open(resolve(ref) / "cooked.tar.gz", "r:gz") as tar:
        try:
            m = tar.getmember(rel)
        except KeyError:
            raise SnapshotError(f"{rel!r} is not in the snapshot") from None
        fh = tar.extractfile(m)
        if fh is None:
            raise SnapshotError(f"{rel!r} is not a file")
        return fh.read()


# --- comparing ---------------------------------------------------------------

@dataclass(frozen=True)
class Change:
    rel: str            # decoded entity path
    where: str          # "Component.field", "item value <label>", or "" for a whole file
    old: str | None     # None: added
    new: str | None     # None: removed


def diff(a: dict, b: dict) -> Iterator[Change]:
    """Every value that differs between two dumps (:func:`collect` output)."""
    ea, eb = a.get("entities", {}), b.get("entities", {})
    for rel in sorted(ea.keys() | eb.keys()):
        if rel not in eb:
            yield Change(rel, "", "file", None)
            continue
        if rel not in ea:
            yield Change(rel, "", None, "file")
            continue
        ca, cb = ea[rel], eb[rel]
        for comp in sorted(ca.keys() | cb.keys()):
            fa, fb = ca.get(comp), cb.get(comp)
            if fa is None or fb is None:
                yield Change(rel, comp, None if fa is None else "part",
                             None if fb is None else "part")
                continue
            for f in sorted(fa.keys() | fb.keys()):
                if fa.get(f) != fb.get(f):
                    yield Change(rel, f"{comp}.{f}", fa.get(f), fb.get(f))
    ia, ib = a.get("items", {}), b.get("items", {})
    for rel in sorted(ia.keys() & ib.keys()):
        va, vb = ia[rel].get("values", {}), ib[rel].get("values", {})
        for label in sorted(va.keys() | vb.keys()):
            if va.get(label) != vb.get(label):
                yield Change(rel, f"item value {label}",
                             None if label not in va else repr(va[label]),
                             None if label not in vb else repr(vb[label]))
        # By name and stat only: `super` is rsmm's own reading of the item, and
        # a better reading is not a change the update made.
        ma = [(m["name"], m["stat"]) for m in ia[rel].get("modifiers", [])]
        mb = [(m["name"], m["stat"]) for m in ib[rel].get("modifiers", [])]
        if ma != mb:
            yield Change(rel, "item modifiers",
                         ", ".join(f"{n}={s}" for n, s in ma),
                         ", ".join(f"{n}={s}" for n, s in mb))
