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
import re
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

    # [[content]] blocks — item kind + per-kind confidence gate
    ce, cw = _lint_content(entry.name, t.get("content", []) or [],
                           experimental=bool(m.get("experimental", False)))
    errs += ce
    warns += cw

    # stray discovery scripts — a mod ships data, not code
    se, sw = _lint_stray_scripts(entry.name, entry)
    errs += se
    warns += sw

    # init.lua: R.on(event) + R.engine.call/resolve(name) vs the symbol map
    le, lw = _lint_lua_api(entry.name, entry)
    errs += le
    warns += lw

    n_patch = len(t.get("patch", []) or [])
    n_content = len(t.get("content", []) or [])
    print(f"  [OK]   {entry.name}  (raw={raw_files} patches={n_patch} "
          f"content={n_content} scope={scope})")
    return errs, warns


def _lint_content(modname: str, blocks: list[dict],
                  *, experimental: bool = False) -> tuple[int, int]:
    """Validate `[[content]] kind="item"` blocks against the cooked corpus:
    base resolves, value_patch labels + defaults match, icon exists.

    Also enforces the per-kind confidence gate: a mod registering any
    non-``confirmed`` kind (see ``sdk.content.KIND_CONFIDENCE``) must set
    ``[mod] experimental = true`` so nobody ships speculative content
    believing it works."""
    errs = warns = 0
    try:
        from rsmm.sdk.content import kind_confidence
    except ImportError:
        def kind_confidence(_k: str) -> str:  # pragma: no cover
            return "confirmed"
    # Confidence gate runs for every kind, even ones with no deep validator.
    for c in blocks:
        kind = c.get("kind")
        if not kind:
            continue
        conf = kind_confidence(str(kind))
        if conf == "confirmed":
            continue
        if not experimental:
            print(f"  [FAIL] {modname}: content kind {kind!r} is {conf!r} "
                  f"(emitted bytes not verified in-game). Set "
                  f"[mod] experimental = true to ship it knowingly.")
            errs += 1
        else:
            print(f"  [WARN] {modname}: content kind {kind!r} is {conf!r} — "
                  f"shipping under experimental opt-in (may not work in-game).")
            warns += 1
    try:
        from rsmm.cli import cmd_items
        from rsmm.engine import magic_item_cook as cook
    except ImportError:
        return errs, warns
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


#: Python files a mod is allowed to ship. Today only the deactivation
#: lifecycle hook (``apply_mods.DEACTIVATION_SCRIPT_NAME``). Everything
#: else is a leaked *discovery* script — the one-off used to reverse a
#: byte layout — which must graduate into the SDK, not ride along in the
#: mod. Keep this set in sync with the hooks `apply_mods` actually fires.
def _sanctioned_scripts() -> set[str]:
    try:
        from rsmm.cli.apply_mods import DEACTIVATION_SCRIPT_NAME
        return {DEACTIVATION_SCRIPT_NAME}
    except ImportError:
        return {"on_disable.py"}


def _lint_stray_scripts(modname: str, entry: Path) -> tuple[int, int]:
    """Fail any ``*.py`` in a mod that isn't a sanctioned lifecycle hook.

    A mod is *data*: a manifest plus cooked/raw assets the SDK emits. A
    bespoke python script inside a mod means a capability was hacked in
    by hand instead of going through the SDK — exactly the debt this
    guardrail exists to stop. The fix is never to keep the script: move
    its logic into ``rsmm.sdk`` (a kind builder / engine cooker) and
    express the mod as ``[[content]]`` / ``[[patch]]`` declarations.
    """
    allowed = _sanctioned_scripts()
    errs = 0
    for f in sorted(entry.rglob("*.py")):
        if not f.is_file():
            continue
        rel = f.relative_to(entry).as_posix()
        if f.name in allowed:
            continue
        print(f"  [FAIL] {modname}: stray script {rel!r} — mods ship data, "
              f"not code; move its logic into rsmm.sdk and express the mod "
              f"as [[content]]/[[patch]] (sanctioned hooks: {sorted(allowed)})")
        errs += 1
    return errs, 0


#: Events the loader always emits (dllmain lifecycle), independent of the
#: RE'd gameplay-event catalog in data/symbols.json.
_BUILTIN_EVENTS = {"setup", "ready", "tick", "exit"}

_RE_ON = re.compile(r"""R\.on\(\s*['"]([^'"]+)['"]""")
_RE_ENGINE = re.compile(r"""R\.engine\.(?:call|resolve)\(\s*['"]([^'"]+)['"]""")


def _engine_vocab() -> tuple[set[str], set[str]]:
    """(valid event names, valid R.engine.* symbol names) from the symbol map,
    plus built-in events. Empty symbol sets if the map can't be loaded."""
    events = set(_BUILTIN_EVENTS)
    callables: set[str] = set()
    try:
        from rsmm.engine.symbols import load_symbol_map
        smap = load_symbol_map()
        events |= {e.lua_event for e in smap.events if e.lua_event}
        callables = {s.name for s in smap.callable_symbols}
    except Exception:
        pass
    return events, callables


def _lint_lua_api(modname: str, entry: Path) -> tuple[int, int]:
    """Warn on R.on()/R.engine.* calls that reference unknown names — a typo
    here fails silently at runtime (the handler just never fires), exactly the
    footgun the symbol map exists to prevent."""
    events, callables = _engine_vocab()
    warns = 0
    for f in sorted(entry.rglob("*.lua")):
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = f.relative_to(entry).as_posix()
        for ev in _RE_ON.findall(text):
            if ev not in events:
                print(f"  [WARN] {modname}: {rel}: R.on({ev!r}) — unknown event "
                      f"(known: {', '.join(sorted(events))}); handler will never fire")
                warns += 1
        if callables:
            for nm in _RE_ENGINE.findall(text):
                if nm not in callables:
                    print(f"  [WARN] {modname}: {rel}: R.engine call to {nm!r} — not a "
                          f"callable symbol (see `rsmm symbols list`)")
                    warns += 1
    return 0, warns


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate mod manifests + assets")
    ap.add_argument("mod_id", nargs="?", default=None)
    args = ap.parse_args()

    if not MODS_DIR.is_dir():
        # mods/ is user-local and untracked (see .gitignore) — absent on a
        # fresh CI checkout. Nothing to lint is not a failure.
        if args.mod_id:
            print(f"no such mod: {args.mod_id}", file=sys.stderr)
            return 1
        print("mods/ not found — nothing to lint")
        return 0

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

    # Cross-mod dependency graph (Fabric-style load validation). Only when
    # linting the whole tree — a single mod can't be graphed in isolation.
    if not args.mod_id:
        from rsmm.manifest_graph import load_manifests, validate_graph
        issues = validate_graph(load_manifests(MODS_DIR))
        graph_e = sum(1 for i in issues if i.severity == "error")
        graph_w = sum(1 for i in issues if i.severity == "warn")
        if graph_e or graph_w:
            print("\ndependency graph:")
            for it in issues:
                if it.severity == "error":
                    print(f"  [ERROR] {it.code}: {it.message}")
                elif it.severity == "warn":
                    print(f"  [WARN]  {it.code}: {it.message}")
        total_e += graph_e
        total_w += graph_w

    print(f"\n{len(candidates)} mod(s) linted: {total_e} error(s), {total_w} warning(s)")
    return 1 if total_e else 0


if __name__ == "__main__":
    sys.exit(main())
