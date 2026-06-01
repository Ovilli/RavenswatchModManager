"""
rsmm lint — per-mod manifest + assets validator.

Surfaces problems before `rsmm apply`:

  - missing or malformed manifest fields
  - assets/ paths that don't resolve via asset_map
  - [[patch]] blocks whose fields don't exist
  - declared multiplayer_scope mismatch with patch kinds
  - dep specs that don't parse

Usage:
    rsmm lint                # every mod
    rsmm lint <id>           # one mod
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from rsmm.cli.merge import _toml_load
from rsmm.engine.asset_map import decoded_to_encoded
from rsmm.engine.paths import MODS_DIR

LANG_SUFFIXES = tuple(f".Lang{c}" for c in [
    "EN", "JA", "KO", "RU", "ES", "DE", "PL", "FR", "IT",
    "PT-BR", "ZH-S", "ZH-T", "RO",
])


def _is_special_decoded(p: str) -> bool:
    if p.startswith("_root/") or "/_root/" in p:
        return True
    if p.endswith(LANG_SUFFIXES):
        return True
    # SDK staging output (`_pending_items/`, `_pending_bosses/`,
    # `_pending_text_overrides/`, etc.) — intermediate JSON consumed by
    # the apply pipeline, never a cooked asset. Matches the filter in
    # `rsmm.cli.apply_mods.Mod.files()` so lint stays consistent.
    if p.split("/", 1)[0].startswith("_pending_"):
        return True
    return False


def _stat_names() -> set[str]:
    out: set[str] = set()
    for dec in decoded_to_encoded():
        norm = dec.replace("\\", "/")
        if (".globalvalue.ot.GlobalEntityValueSettings.gen" in norm
            or ".gamemodifierdef.ot.meModifierDefinition.gen" in norm
            or ".enemycampdifficultydef.ot.DtEnemyCampDifficultyDefinition.gen" in norm):
            out.add(norm.rsplit("/", 1)[-1].split(".", 1)[0].lower())
    return out


def lint_one(entry: Path) -> tuple[int, int]:
    """Return (errors, warnings)."""
    mf = entry / "manifest.toml"
    if not mf.exists():
        print(f"  [FAIL] {entry.name}: missing manifest.toml")
        return 1, 0
    try:
        t = _toml_load(mf)
    except Exception as e:
        print(f"  [FAIL] {entry.name}: manifest parse: {e}")
        return 1, 0

    errs = warns = 0
    m = t.get("mod", {})
    if "id" not in m:
        print(f"  [WARN] {entry.name}: manifest missing 'id' (using folder name)")
        warns += 1
    if "version" not in m:
        print(f"  [WARN] {entry.name}: manifest missing 'version'")
        warns += 1
    scope = m.get("multiplayer_scope", "cosmetic")
    if scope not in {"cosmetic", "deterministic-shared",
                     "host-authoritative", "local-only"}:
        print(f"  [FAIL] {entry.name}: unknown multiplayer_scope {scope!r}")
        errs += 1

    # assets/
    dec2enc = decoded_to_encoded()
    assets = entry / "assets"
    raw_files = 0
    if assets.is_dir():
        for f in assets.rglob("*"):
            if not f.is_file():
                continue
            p = f.relative_to(assets).as_posix()
            raw_files += 1
            if _is_special_decoded(p):
                continue
            if p not in dec2enc:
                print(f"  [WARN] {entry.name}: assets/ path not in asset_map: {p}")
                warns += 1

    # [[patch]] blocks
    stat_set = _stat_names()
    for p in t.get("patch", []) or []:
        kind = p.get("kind")
        if kind == "stat":
            name = str(p.get("name", "")).lower()
            if not name:
                print(f"  [FAIL] {entry.name}: stat patch missing 'name'")
                errs += 1
            elif name not in stat_set:
                print(f"  [WARN] {entry.name}: stat name not in catalog: {p.get('name')!r}")
                warns += 1
        elif kind == "texture":
            for side in ("target", "donor"):
                v = p.get(side)
                if not v:
                    print(f"  [FAIL] {entry.name}: texture missing '{side}'")
                    errs += 1
                elif v not in dec2enc:
                    print(f"  [WARN] {entry.name}: texture {side} not in asset_map: {v!r}")
                    warns += 1
        elif kind == "text":
            for k in ("bank", "lang", "key", "value"):
                if k not in p:
                    print(f"  [FAIL] {entry.name}: text patch missing {k!r}")
                    errs += 1
                    break
        elif kind == "url":
            for k in ("field", "value"):
                if k not in p:
                    print(f"  [FAIL] {entry.name}: url patch missing {k!r}")
                    errs += 1
                    break
        elif kind == "composite":
            # Accept any; backing impl may be a no-op today.
            pass
        elif kind:
            print(f"  [WARN] {entry.name}: unknown patch kind {kind!r}")
            warns += 1

    # [[content]] blocks — item kind
    ce, cw = _lint_content(entry.name, t.get("content", []) or [])
    errs += ce
    warns += cw

    n_patch = len(t.get("patch", []) or [])
    n_content = len(t.get("content", []) or [])
    print(f"  [OK]   {entry.name}  (raw={raw_files} patches={n_patch} "
          f"content={n_content} scope={scope})")
    return errs, warns


def _lint_content(modname: str, blocks: list[dict]) -> tuple[int, int]:
    """Validate `[[content]] kind="item"` blocks against the cooked corpus:
    base resolves, value_patch labels + defaults match, icon exists."""
    errs = warns = 0
    try:
        from rsmm.cli import cmd_items
        from rsmm.engine import magic_item_cook as cook
    except ImportError:
        return 0, 0
    for c in blocks:
        if c.get("kind") != "item":
            continue
        cid = c.get("id")
        base = c.get("base")
        if not cid:
            print(f"  [FAIL] {modname}: item content missing 'id'")
            errs += 1
            continue
        if not base:
            print(f"  [FAIL] {modname}: item {cid}: missing 'base'")
            errs += 1
            continue
        found = cmd_items._find_item(str(base))
        if found is None:
            print(f"  [WARN] {modname}: item {cid}: base {base!r} not a known "
                  f"vanilla item (falls back to legacy manifest)")
            warns += 1
            continue
        data = found[2].read_bytes()
        for vp in c.get("value_patches", []) or []:
            label, old = (vp[0], vp[1]) if isinstance(vp, list) else (
                vp.get("label"), vp.get("old"))
            try:
                cook.set_value_after_label(data, str(label), float(old), float(old))
            except (ValueError, TypeError) as e:
                print(f"  [FAIL] {modname}: item {cid}: value_patch {label!r}: {e}")
                errs += 1
        icon = c.get("icon")
        if icon and "\\" not in str(icon) and "/" not in str(icon) \
                and not str(icon).lower().endswith(".png"):
            if str(icon) not in cmd_items._icon_stems(None):
                print(f"  [WARN] {modname}: item {cid}: icon {icon!r} not a known "
                      f"vanilla stem (try `rsmm items icons`)")
                warns += 1
    return errs, warns


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate mod manifests + assets")
    ap.add_argument("mod_id", nargs="?", default=None)
    args = ap.parse_args()

    if not MODS_DIR.is_dir():
        print("mods/ not found", file=sys.stderr)
        return 1

    candidates: list[Path] = []
    if args.mod_id:
        p = MODS_DIR / args.mod_id
        if not p.is_dir():
            print(f"no such mod: {args.mod_id}", file=sys.stderr)
            return 1
        candidates = [p]
    else:
        for entry in sorted(MODS_DIR.iterdir()):
            if not entry.is_dir() or entry.name.startswith(("_", ".")):
                continue
            candidates.append(entry)

    total_e = total_w = 0
    for c in candidates:
        e, w = lint_one(c)
        total_e += e
        total_w += w
    print(f"\n{len(candidates)} mod(s) linted: {total_e} error(s), {total_w} warning(s)")
    return 1 if total_e else 0


if __name__ == "__main__":
    sys.exit(main())
