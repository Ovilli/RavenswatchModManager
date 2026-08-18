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
    [[patch]] kind="ot"       selector=<label> field=<name> value=<v>
                              [file=<game-relative .ot>] [selector_field=<name>]

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
from rsmm.engine.ot_patch import OtPatchError, apply_edits
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


def _toml_load(p: Path) -> dict:
    """Parse a mod manifest. Raises on malformed input, like every other reader.

    This used to fall back to `_toml_fallback`, an in-house regex parser,
    whenever tomllib reported malformed input. That fallback was written for
    "no TOML backend installed" — impossible here, since tomllib is stdlib and
    the project requires 3.11+ — so the only way it ever ran was on a manifest
    tomllib had already rejected. It then accepted the file anyway, using
    *different* semantics (`on`/`off`/`yes`/`no` as booleans, which TOML does
    not have) and keeping whatever its regex could scrape.

    The result was two components disagreeing about whether a mod is valid:
    `apply_mods.discover_mods` skipped it with a decode error while
    `collect_patches` merged `[[patch]]` blocks out of it — including fields
    whose values were parse debris. `collect_patches` already catches
    TOMLDecodeError and skips the mod with a message, which is the behaviour
    the comment there always claimed.
    """
    return tomllib.loads(p.read_text(encoding="utf-8"))


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
        # A manifest that does not parse contributes no patches, matching what
        # `apply_mods.discover_mods` does with the same file. OSError covers
        # permission / disappearance races.
        try:
            t = _toml_load(mf)
        except (tomllib.TOMLDecodeError, OSError) as e:
            print(f"  [merge] skip {entry.name}: {e}", file=sys.stderr)
            continue
        mod_meta = t.get("mod", {})
        raw_enabled = mod_meta.get("enabled", True)
        is_on = (
            raw_enabled if isinstance(raw_enabled, bool)
            else str(raw_enabled).lower() in ("1", "true", "yes", "on")
        )
        if not is_on:
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
        per_target.setdefault(str(p.data.get("name", "")).lower(), []).append(p)

    written = 0
    for short, group in per_target.items():
        candidates = by_short.get(short, [])
        if not candidates:
            print(f"  [merge] stat: unknown name {group[0].data.get('name', '<missing>')!r}",
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
        per_target.setdefault(str(p.data.get("target", "")).replace("\\", "/"), []).append(p)

    written = 0
    for target, group in per_target.items():
        if target not in dec2enc:
            print(f"  [merge] texture: unknown target {target!r}",
                  file=sys.stderr)
            continue
        donors = {p.mod_id: str(p.data.get("donor", "")).replace("\\", "/") for p in group}
        if len(set(donors.values())) > 1:
            conflicts.append(("texture", target, donors))
        winner = group[-1]
        donor = str(winner.data.get("donor", "")).replace("\\", "/")
        donor_enc = dec2enc.get(donor)
        if not donor_enc:
            print(f"  [merge] texture: donor not in asset_map: {donor!r}",
                  file=sys.stderr)
            continue
        donor_parts = donor_enc.split("\\")
        if any(p == ".." for p in donor_parts):
            print(f"  [merge] texture: refusing path with traversal segments: {donor_enc!r}",
                  file=sys.stderr)
            continue
        src = cooking / Path(*donor_parts)
        # Read the donor's VANILLA bytes, not whatever is on disk right now.
        #
        # `cooking` is the live directory, so if any mod (or an earlier apply)
        # has already replaced the donor, this copies the MODDED bytes and the
        # result depends on mod order. `apply` keeps the original beside every
        # file it overrides as <file>.rsmm.bak, so when that exists it IS the
        # pristine donor and is what a texture patch means by "the game's own
        # asset". Without this, enabling two texture mods could chain one into
        # the other, and re-applying could propagate a previous result.
        pristine = src.parent / (src.name + ".rsmm.bak")
        if pristine.exists():
            src = pristine
        if not src.exists():
            print(f"  [merge] texture: donor missing on disk: {src}",
                  file=sys.stderr)
            continue
        dest = out_assets / target
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        written += 1
    return written


#: The plaintext `.ot` an `ot` patch edits when it does not name one. It is the
#: only uncooked file mods have a reason to touch today (entity-value modifier
#: descriptors, friendly-fire factors, the forced-seed option).
DEFAULT_OT_FILE = "DarkTalesResources/ApplicationSettings.ot"


def _ot_patches(patches: list[_Patch], game_dir: Path, out_assets: Path,
                conflicts: list) -> int:
    """Compose `kind="ot"` patches: field-level edits to the game's own
    plaintext `.ot` files, installed back through the `_root/` channel.

    The alternative — and what mods had to do before this — is shipping a whole
    copy of the game's file, which redistributes a game asset and reverts every
    unrelated change the next patch makes to it. Here the mod declares three
    strings and the game's own bytes are the base.
    """
    ots = [p for p in patches if p.kind == "ot"]
    if not ots:
        return 0

    per_file: dict[str, list[_Patch]] = {}
    for p in _ranked(ots):
        rel = str(p.data.get("file") or DEFAULT_OT_FILE).replace("\\", "/").strip("/")
        per_file.setdefault(rel, []).append(p)

    written = 0
    for rel, group in per_file.items():
        parts = Path(rel).parts
        if Path(rel).is_absolute() or any(seg == ".." for seg in parts):
            print(f"  [merge] ot: refusing path with traversal segments: {rel!r}",
                  file=sys.stderr)
            continue
        src = game_dir / Path(*parts)
        # The game's PRISTINE bytes, exactly as the texture merge does it: once
        # an apply has installed a previous result, `src` is that result, and
        # composing on top of it would make the outcome depend on how many
        # times apply has run.
        pristine = src.parent / (src.name + ".rsmm.bak")
        if pristine.exists():
            src = pristine
        if not src.exists():
            print(f"  [merge] ot: file not found in the game install: {rel!r}",
                  file=sys.stderr)
            continue

        # Same field, two mods, different values: report it and let the later
        # mod win, like every other kind here.
        seen: dict[tuple[str, str, str], dict[str, object]] = {}
        for p in group:
            key = (str(p.data.get("selector_field") or "m_sLabel"),
                   str(p.data.get("selector", "")),
                   str(p.data.get("field", "")))
            seen.setdefault(key, {})[p.mod_id] = p.data.get("value")
        for key, owners in seen.items():
            if len({repr(v) for v in owners.values()}) > 1:
                conflicts.append(("ot", f"{rel}:{key[1]}:{key[2]}", dict(owners)))

        # `surrogateescape` so a byte the file's declared encoding cannot
        # represent survives the round trip untouched — an edit must never
        # rewrite a part of the file it was not asked about.
        text = src.read_text(encoding="utf-8", errors="surrogateescape")
        edits = []
        for p in group:
            missing = [k for k in ("selector", "field") if not p.data.get(k)]
            if missing or "value" not in p.data:
                print(f"  [merge] ot {p.mod_id}: patch missing "
                      f"{', '.join(missing or ['value'])}", file=sys.stderr)
                continue
            edits.append({
                "selector": p.data["selector"],
                "field": p.data["field"],
                "value": p.data["value"],
                "selector_field": p.data.get("selector_field"),
            })
        if not edits:
            continue
        try:
            text, done = apply_edits(text, edits)
        except OtPatchError as e:
            # Refuse the FILE, not just the edit: a half-applied set of edits is
            # a config nobody wrote, and the author's next run would be
            # debugging a state that exists in no manifest.
            print(f"  [merge] ot {rel}: {e}", file=sys.stderr)
            continue
        for ed in done:
            print(f"  [merge] ot {rel}: {ed.selector}.{ed.field} "
                  f"{ed.old} -> {ed.new}  (line {ed.line})")

        dest = out_assets / "_root" / Path(*parts)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(text, encoding="utf-8", errors="surrogateescape")
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
    written += _ot_patches(patches, game_dir, out_assets, conflicts)

    # text/url patches: not yet merged at the cooked-byte level — point
    # users at the dedicated single-mod tools for those kinds.
    unsupported = sorted({p.kind for p in patches
                          if p.kind not in {"stat", "texture", "ot"}})
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
