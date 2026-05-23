"""
Patch-merge layer.

Reads `[[patch]]` blocks from every enabled mod's manifest.toml,
groups by target cooked file, composes one coherent output per
target, and writes a synthetic mod under `mods/_merged/`. `rsmm apply`
then installs that synthetic mod normally.

Two mods touching *different* fields of the same cooked file both
take effect. Two mods touching the *same* field log a conflict; the
later mod by (load_order, id) wins.

Supported patch kinds today:

    [[patch]] kind="stat"     name=<field>  [value=N] [min=N] [max=N]
    [[patch]] kind="texture"  target=<decoded_path>  donor=<decoded_path>

`text` and `url` patches are passed through to dedicated single-mod
files (no merge) until their writers are factored out. Conflicts
between text/url edits across mods still produce a last-wins warning
at apply time.
"""

from __future__ import annotations

import re
import shutil
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from rsmm.engine.asset_map import decoded_to_encoded, encoded_to_decoded
from rsmm.engine.paths import (
    COOKING_SUBDIR,
    MODS_DIR,
)
from rsmm.engine.paths import (
    DEFAULT_GAME_DIR as DEFAULT_GAME,
)
from rsmm.engine.stat_schemas import index_entries, patch_field

MERGED_MOD_ID = "_merged"


@dataclass
class _Patch:
    mod_id: str
    load_order: int
    kind: str
    data: dict


def _toml_fallback(p: Path) -> dict:
    """Minimal subset parser for [mod] + [[patch]] manifests, used when
    neither tomllib (3.11+) nor tomli is importable."""
    out: dict = {"mod": {}, "patch": []}
    cur_table: str | None = None
    cur_array_entry: dict | None = None
    for line in p.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        m = re.match(r"\[\[\s*([A-Za-z_]+)\s*\]\]", s)
        if m:
            cur_array_entry = {}
            out.setdefault(m.group(1), []).append(cur_array_entry)
            cur_table = None
            continue
        m = re.match(r"\[\s*([A-Za-z_]+)\s*\]", s)
        if m:
            cur_table = m.group(1)
            out.setdefault(cur_table, {})
            cur_array_entry = None
            continue
        m = re.match(r"([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.+)$", s)
        if not m:
            continue
        k, raw = m.group(1), m.group(2).strip()
        # Strip inline comments (everything after the first unquoted space + #)
        raw = raw.split(" #")[0].split("\t#")[0].rstrip()
        if raw.startswith('"') and raw.endswith('"'):
            v: object = raw[1:-1]
        elif raw in {"true", "false"}:
            v = raw == "true"
        else:
            try:
                v = int(raw) if raw.lstrip("-+").isdigit() else float(raw)
            except ValueError:
                v = raw
        target = cur_array_entry if cur_array_entry is not None else out.get(cur_table or "mod", {})
        target[k] = v
    return out


def _toml_load(p: Path) -> dict:
    # Three-way fallback: prefer stdlib tomllib, then the third-party
    # tomli backend, finally the in-house _toml_fallback (which only
    # understands the subset of TOML that mod manifests actually use).
    # We catch ImportError (backend not installed) and TOMLDecodeError
    # (backend reports malformed input) so the fallback gets a chance —
    # bare `except Exception` here silently swallowed programmer errors.
    import tomllib
    try:
        return tomllib.loads(p.read_text(encoding="utf-8"))
    except (ImportError, tomllib.TOMLDecodeError):
        pass
    try:
        import tomli
    except ImportError:
        return _toml_fallback(p)
    try:
        return tomli.loads(p.read_text(encoding="utf-8"))
    except tomli.TOMLDecodeError:
        return _toml_fallback(p)


def collect_patches() -> list[_Patch]:
    out: list[_Patch] = []
    if not MODS_DIR.is_dir():
        return out
    for entry in sorted(MODS_DIR.iterdir()):
        if not entry.is_dir() or entry.name.startswith(("_", ".")):
            continue
        mf = entry / "manifest.toml"
        if not mf.exists():
            continue
        # _toml_load itself falls back through every parser before
        # raising; a TOMLDecodeError that reaches here means even the
        # in-house fallback parser couldn't make sense of the manifest.
        # OSError covers permission / disappearance races.
        try:
            t = _toml_load(mf)
        except (tomllib.TOMLDecodeError, OSError) as e:
            print(f"  [merge] skip {entry.name}: {e}", file=sys.stderr)
            continue
        mod_meta = t.get("mod", {})
        if not mod_meta.get("enabled", True):
            continue
        mid = mod_meta.get("id") or entry.name
        order = int(mod_meta.get("load_order", 100))
        for p in t.get("patch", []) or []:
            kind = p.get("kind")
            if not kind:
                continue
            data = {k: v for k, v in p.items() if k != "kind"}
            out.append(_Patch(mid, order, kind, data))
    return out


def _ranked(items: list[_Patch]) -> list[_Patch]:
    """Stable sort by (load_order, mod_id) so the *last* item wins on
    same-field conflict."""
    return sorted(items, key=lambda x: (x.load_order, x.mod_id))


def _stat_patches(patches: list[_Patch], cooking: Path, out_assets: Path,
                  conflicts: list) -> int:
    stats = [p for p in patches if p.kind == "stat"]
    if not stats:
        return 0
    entries = index_entries(cooking, encoded_to_decoded())
    by_short: dict[str, list] = {}
    for e in entries:
        by_short.setdefault(e.short_name.lower(), []).append(e)

    per_target: dict[str, list[_Patch]] = {}
    for p in _ranked(stats):
        per_target.setdefault(str(p.data["name"]).lower(), []).append(p)

    written = 0
    for short, group in per_target.items():
        candidates = by_short.get(short, [])
        if not candidates:
            print(f"  [merge] stat: unknown name {group[0].data['name']!r}",
                  file=sys.stderr)
            continue
        wanted_fields: set[str] = set()
        for p in group:
            for k in p.data:
                if k != "name":
                    wanted_fields.add(k)
        entry = candidates[0]
        for c in candidates:
            sf = {fn for fn, _, _ in c.schema.fields}
            if wanted_fields and wanted_fields <= sf:
                entry = c
                break

        # Compose: per-field winner + record conflicts
        per_field_seen: dict[str, dict[str, float]] = {}
        per_field_final: dict[str, float] = {}
        for p in group:
            for fn, v in p.data.items():
                if fn == "name" or not isinstance(v, (int, float)):
                    continue
                per_field_seen.setdefault(fn, {})[p.mod_id] = float(v)
                per_field_final[fn] = float(v)
        for fn, m in per_field_seen.items():
            if len({round(v, 6) for v in m.values()}) > 1:
                conflicts.append(("stat", f"{short}:{fn}", dict(m)))

        data = entry.cooked_path.read_bytes()
        for fn, v in per_field_final.items():
            try:
                data = patch_field(data, entry.schema, fn, v)
            except ValueError as e:
                print(f"  [merge] stat {short}:{fn}: {e}", file=sys.stderr)
                continue
        dest = out_assets / entry.decoded_relpath
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        written += 1
    return written


def _texture_patches(patches: list[_Patch], cooking: Path, out_assets: Path,
                     conflicts: list) -> int:
    texs = [p for p in patches if p.kind == "texture"]
    if not texs:
        return 0
    dec2enc = decoded_to_encoded()
    per_target: dict[str, list[_Patch]] = {}
    for p in _ranked(texs):
        per_target.setdefault(str(p.data["target"]).replace("\\", "/"), []).append(p)

    written = 0
    for target, group in per_target.items():
        if target not in dec2enc:
            print(f"  [merge] texture: unknown target {target!r}",
                  file=sys.stderr)
            continue
        donors = {p.mod_id: str(p.data["donor"]).replace("\\", "/") for p in group}
        if len(set(donors.values())) > 1:
            conflicts.append(("texture", target, donors))
        winner = group[-1]
        donor = str(winner.data["donor"]).replace("\\", "/")
        donor_enc = dec2enc.get(donor)
        if not donor_enc:
            print(f"  [merge] texture: donor not in asset_map: {donor!r}",
                  file=sys.stderr)
            continue
        src = cooking / Path(*donor_enc.split("\\"))
        if not src.exists():
            print(f"  [merge] texture: donor missing on disk: {src}",
                  file=sys.stderr)
            continue
        dest = out_assets / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        written += 1
    return written


def build_merged_mod(game_dir: Path) -> tuple[Path | None, list]:
    """Compose every supported [[patch]] across mods/ into
    `mods/_merged/`. Returns (path or None, conflict-report list)."""
    cooking = game_dir / COOKING_SUBDIR
    patches = collect_patches()
    if not patches:
        out_root = MODS_DIR / MERGED_MOD_ID
        if out_root.exists():
            shutil.rmtree(out_root)
        return None, []

    out_root = MODS_DIR / MERGED_MOD_ID
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)
    out_assets = out_root / "assets"
    out_assets.mkdir()

    conflicts: list = []
    written = 0
    written += _stat_patches(patches, cooking, out_assets, conflicts)
    written += _texture_patches(patches, cooking, out_assets, conflicts)

    # text/url patches: not yet merged at the cooked-byte level — point
    # users at the dedicated single-mod tools for those kinds.
    unsupported = sorted({p.kind for p in patches
                          if p.kind not in {"stat", "texture"}})
    for k in unsupported:
        owners = sorted({p.mod_id for p in patches if p.kind == k})
        print(f"  [merge] {k!r} patches are not yet composed in mods/_merged "
              f"(owners: {', '.join(owners)}). "
              f"Use `./rsmm {k}` to ship them as separate mods.",
              file=sys.stderr)

    if written == 0:
        shutil.rmtree(out_root)
        return None, conflicts

    (out_root / "manifest.toml").write_text(
        "# Auto-generated by rsmm merge. Do not edit by hand.\n"
        "[mod]\n"
        f'id          = "{MERGED_MOD_ID}"\n'
        'name        = "RSMM patch-merge output"\n'
        'version     = "0.0.0"\n'
        'author      = "rsmm"\n'
        'description = "Composed [[patch]] blocks from every enabled mod."\n'
        "enabled     = true\n"
        "load_order  = 9999\n",
        encoding="utf-8",
    )
    return out_root, conflicts


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Compose [[patch]] blocks across mods/ into mods/_merged/",
    )
    ap.add_argument("--game-dir", type=Path, default=DEFAULT_GAME)
    args = ap.parse_args()
    out, conflicts = build_merged_mod(args.game_dir)
    if out is None:
        print("No supported [[patch]] blocks found.")
        return 0
    print(f"Built {out}")
    if conflicts:
        print(f"\n{len(conflicts)} conflict(s) — later mod won:")
        for kind, key, m in conflicts:
            print(f"  [{kind}] {key}  {m}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
