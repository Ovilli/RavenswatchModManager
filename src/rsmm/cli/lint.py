"""
rsmm lint — per-mod manifest + assets validator.

Surfaces problems before `rsmm apply`:

  - missing or malformed manifest fields
  - assets/ paths that don't resolve via asset_map
  - raw assets/ overrides that no-op, edit a shadowed value, or re-frame the
    container (needs the vanilla corpus; skipped when it isn't on disk)
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

from rsmm.cli import _term
from rsmm.cli.merge import _toml_load
from rsmm.engine.asset_map import decoded_to_encoded
from rsmm.engine.paths import MODS_DIR

#: Presentation only. `Style()` self-disables when stdout isn't a TTY (or
#: NO_COLOR is set), so piped/captured output stays byte-identical to the
#: uncoloured text every CI grep and test already matches on.
_ST = _term.Style()
_ST_ERR = _term.Style(stream=sys.stderr)

# Severity tokens pre-styled once. The surrounding spacing is kept at the call
# sites so the plain-text column layout is unchanged.
_T_FAIL = _ST.err("[FAIL]")
_T_ERR = _ST.err("[ERR]")
_T_WARN = _ST.warn("[WARN]")
_T_OK = _ST.ok("[OK]")
_T_ERROR = _ST.err("[ERROR]")

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
    mod_s = _ST.bold(entry.name)
    if not mf.exists():
        print(f"  {_T_FAIL} {mod_s}: missing manifest.toml")
        return 1, 0
    try:
        t = _toml_load(mf)
    except Exception as e:
        print(f"  {_T_FAIL} {mod_s}: manifest parse: {_ST.dim(str(e))}")
        return 1, 0

    errs = warns = 0
    m = t.get("mod", {})
    if "id" not in m:
        print(f"  {_T_WARN} {mod_s}: manifest missing 'id' "
              f"{_ST.dim('(using folder name)')}")
        warns += 1
    if "version" not in m:
        print(f"  {_T_WARN} {mod_s}: manifest missing 'version'")
        warns += 1
    warns += _lint_store_metadata(mod_s, m)
    scope = m.get("multiplayer_scope", "cosmetic")
    if scope not in {"cosmetic", "deterministic-shared",
                     "host-authoritative", "local-only"}:
        print(f"  {_T_FAIL} {mod_s}: unknown multiplayer_scope {_ST.accent(repr(scope))}")
        errs += 1

    # [overlay] — a mod-declared HUD. Validated here rather than at runtime
    # because the failure is otherwise invisible: the desktop app would list
    # the overlay, refuse to open it, and the author would have no idea which
    # field was wrong.
    if "overlay" in t:
        from rsmm.cli.cmd_overlay import OverlayError, parse_spec
        try:
            parse_spec(t.get("overlay"), mod_id=str(m.get("id", entry.name)))
        except OverlayError as e:
            # parse_spec prefixes its own mod id (its messages also reach the
            # CLI and the desktop app, where there is no other context); here
            # the line already names the mod, so trim the repeat.
            detail = str(e).split(": ", 1)[-1]
            print(f"  {_T_FAIL} {mod_s}: {detail}")
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
                print(f"  {_T_WARN} {mod_s}: assets/ path not in asset_map: "
                      f"{_ST.accent(p)}")
                warns += 1

    # raw assets/ overrides vs the vanilla corpus
    re_, rw = _lint_raw_overrides(entry.name, entry)
    errs += re_
    warns += rw

    # [[patch]] blocks
    stat_set = _stat_names()
    for p in t.get("patch", []) or []:
        kind = p.get("kind")
        if kind == "stat":
            name = str(p.get("name", "")).lower()
            if not name:
                print(f"  {_T_FAIL} {mod_s}: stat patch missing 'name'")
                errs += 1
            elif name not in stat_set:
                print(f"  {_T_WARN} {mod_s}: stat name not in catalog: "
                      f"{_ST.accent(repr(p.get('name')))}")
                warns += 1
        elif kind == "texture":
            for side in ("target", "donor"):
                v = p.get(side)
                if not v:
                    print(f"  {_T_FAIL} {mod_s}: texture missing '{side}'")
                    errs += 1
                elif v not in dec2enc:
                    print(f"  {_T_WARN} {mod_s}: texture {side} not in asset_map: "
                          f"{_ST.accent(repr(v))}")
                    warns += 1
        elif kind == "text":
            for k in ("bank", "lang", "key", "value"):
                if k not in p:
                    print(f"  {_T_FAIL} {mod_s}: text patch missing {_ST.accent(repr(k))}")
                    errs += 1
                    break
        elif kind == "ot":
            # An `ot` patch names a field inside a plaintext .ot the GAME ships,
            # so the value it sets is checked against the real file at merge
            # time. What lint can catch without the install is a block that is
            # missing the three fields the patch is made of — `value` may
            # legitimately be 0 or false, so it is tested for PRESENCE.
            for k in ("selector", "field"):
                if not p.get(k):
                    print(f"  {_T_FAIL} {mod_s}: ot patch missing {_ST.accent(repr(k))}")
                    errs += 1
                    break
            else:
                if "value" not in p:
                    print(f"  {_T_FAIL} {mod_s}: ot patch missing {_ST.accent(repr('value'))}")
                    errs += 1
            f = str(p.get("file", "") or "")
            if f.startswith("/") or ".." in Path(f).parts:
                print(f"  {_T_FAIL} {mod_s}: ot patch file must be a relative path "
                      f"inside the install: {_ST.accent(repr(f))}")
                errs += 1
        elif kind == "url":
            for k in ("field", "value"):
                if k not in p:
                    print(f"  {_T_FAIL} {mod_s}: url patch missing {_ST.accent(repr(k))}")
                    errs += 1
                    break
        elif kind == "composite":
            # Accept any; backing impl may be a no-op today.
            pass
        elif kind:
            print(f"  {_T_WARN} {mod_s}: unknown patch kind {_ST.accent(repr(kind))}")
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
    summary = (f"(raw={raw_files} patches={n_patch} "
               f"content={n_content} scope={scope})")
    print(f"  {_T_OK}   {_ST.heading(entry.name)}  {_ST.dim(summary)}")
    return errs, warns


#: Cooked classes whose value nodes the before-END scanner understands. Other
#: raw overrides still get the byte-level checks, just not the value diff.
_ENTITY_SUFFIX = ".EntitySettingsResource.gen"


def _vanilla_root() -> Path | None:
    """Mirrored vanilla corpus, or ``None`` when it isn't on disk.

    ``data/uncooked/`` is game-derived and gitignored, so it is absent in fresh
    clones, in the frozen sidecar, and in git worktrees. Every check below is
    therefore advisory: no corpus means no comparison, never a failure.
    """
    try:
        from rsmm.engine.paths import DATA_DIR
    except ImportError:  # pragma: no cover - paths always importable in practice
        return None
    root = Path(DATA_DIR) / "uncooked"
    return root if root.is_dir() else None


#: Author names the scaffold writes, or that plainly nobody chose. A mod
#: published under one has no attribution at all on its store card.
_PLACEHOLDER_AUTHORS = frozenset({"you", "your name", "author", "me", "unknown", ""})

#: Manifest fields the store and the desktop mod list actually render
#: (`json_bridge.cmd_list`), with what each one is for.
_STORE_FIELDS = (
    ("description", "the store card has nothing to say about this mod"),
    ("tags", "the mod cannot be found by browsing or filtering"),
    ("license", "nobody can tell whether they may redistribute or fork it"),
)


def _lint_store_metadata(mod_s: str, m: dict) -> int:
    """Warn about metadata a published mod needs. Returns the warning count.

    None of this affects whether the mod *works*, which is why it is a warning
    — but all of it is read straight into the store payload and the desktop
    mod list, so a mod missing it installs fine and presents as an unlabelled
    blank. Kept advisory so an unpublished local mod is not nagged into
    failing CI.
    """
    warns = 0
    for field, why in _STORE_FIELDS:
        value = m.get(field)
        if value in (None, "", [], {}):
            print(f"  {_T_WARN} {mod_s}: no {_ST.accent(field)} "
                  f"{_ST.dim('— ' + why)}")
            warns += 1
    author = str(m.get("author", "")).strip().lower()
    if author in _PLACEHOLDER_AUTHORS:
        print(f"  {_T_WARN} {mod_s}: placeholder author "
              f"{_ST.accent(repr(m.get('author', '')))} "
              f"{_ST.dim('— scaffold default, not a real attribution')}")
        warns += 1
    return warns


def _lint_raw_overrides(modname: str, entry: Path, *,
                        vanilla_root: Path | None = None) -> tuple[int, int]:
    """Compare each raw ``assets/`` override against its vanilla twin.

    A raw override is the one modding path with no schema behind it — the mod
    ships finished bytes and ``apply`` copies them over the retail asset, so
    nothing until the game itself ever inspects what changed. Three failures
    are invisible without this check:

    * the override is byte-identical to vanilla (ships, applies, does nothing);
    * it edits a *shadowed* value node, whose inline float the engine ignores
      because the value is sourced from a selector — the mod claims a nerf and
      the number in game never moves;
    * it changes the file length, i.e. it re-framed the container rather than
      patching in place. That can be legitimate (a re-emitted section) but it
      is also how a byte-splice bricks an asset, so it is worth saying out loud.

    Returns ``(errors, warnings)``. Only the shadowed-edit case is an error;
    it is the one where the mod is provably not doing what it says.
    """
    assets = entry / "assets"
    if not assets.is_dir():
        return 0, 0
    root = vanilla_root if vanilla_root is not None else _vanilla_root()
    if root is None:
        return 0, 0
    try:
        from rsmm.engine.talent_values import list_talent_values
    except ImportError:  # pragma: no cover
        return 0, 0

    errs = warns = 0
    mod_s = _ST.bold(modname)
    for f in sorted(assets.rglob("*")):
        if not f.is_file():
            continue
        rel = f.relative_to(assets)
        vanilla = root / rel
        if not vanilla.is_file():
            continue  # new asset, or a family the corpus doesn't mirror
        cur, van = f.read_bytes(), vanilla.read_bytes()
        name = _ST.accent(rel.as_posix())
        if cur == van:
            print(f"  {_T_WARN} {mod_s}: override identical to vanilla "
                  f"{_ST.dim('(applies, changes nothing)')}: {name}")
            warns += 1
            continue
        if len(cur) != len(van):
            hint = (f"({len(van)} -> {len(cur)} bytes; container re-framed, not "
                    f"an in-place edit — test this asset on its own)")
            print(f"  {_T_WARN} {mod_s}: structural override {_ST.dim(hint)}: {name}")
            warns += 1
        if not rel.name.endswith(_ENTITY_SUFFIX):
            continue
        before = {v.label: v for v in list_talent_values(van)}
        after = {v.label: v for v in list_talent_values(cur)}
        changed = [lab for lab, v in before.items()
                   if lab in after and after[lab].value != v.value]
        for lab in changed:
            delta = f"{before[lab].value:g} -> {after[lab].value:g}"
            # Judge the shadow flag on the MOD's bytes, not vanilla's. Clearing
            # the `0e` override sub-field is exactly how a mod makes an inline
            # value authoritative (`talent_values.clear_value_override`), so
            # testing vanilla's flag reported that *successful* fix as an error
            # claiming the edit has no in-game effect — precisely backwards, and
            # unfixable from the mod author's side.
            if after[lab].is_overridden:
                hint = ("its value is sourced from a selector/reference, so the "
                        "inline edit has NO in-game effect")
                print(f"  {_T_ERROR} {mod_s}: {name}: value {_ST.accent(repr(lab))} "
                      f"is shadowed — {_ST.dim(hint)}")
                errs += 1
            elif before[lab].is_overridden:
                note = "override cleared, so the inline value now applies"
                print(f"  {_ST.dim('  ·')} {mod_s}: {name}: "
                      f"{_ST.dim(repr(lab) + ' ' + delta + ' [un-shadowed: ' + note + ']')}")
            else:
                print(f"  {_ST.dim('  ·')} {mod_s}: {name}: "
                      f"{_ST.dim(repr(lab) + ' ' + delta)}")
        # A mod that *enables* the override on a value it did not otherwise
        # change has silently disconnected that number from the asset.
        for lab, post in after.items():
            if lab in before and post.is_overridden and not before[lab].is_overridden:
                print(f"  {_T_WARN} {mod_s}: {name}: value {_ST.accent(repr(lab))} "
                      f"{_ST.dim('was newly shadowed — its inline value no longer applies')}")
                warns += 1
        if not changed:
            # Deliberately not "your edit does nothing": `list_talent_values`
            # only reports *authored magnitude* nodes, so a GUID repoint, a
            # `...Selector` node or a `...Counter` threshold is invisible to it
            # by design. PiperGhostHorde is entirely such edits and was reading
            # as a dead override. Say what was checked, not more.
            print(f"  {_ST.dim('  ·')} {mod_s}: {name}: "
                  f"{_ST.dim('bytes differ, but no tracked magnitude node changed')} "
                  f"{_ST.dim('(GUID/selector/counter edits are not tracked — verify in game)')}")
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
            hint = ("(emitted bytes not verified in-game). Set "
                    "[mod] experimental = true to ship it knowingly.")
            print(f"  {_T_FAIL} {_ST.bold(modname)}: content kind "
                  f"{_ST.accent(repr(kind))} is {_ST.err(repr(conf))} {_ST.dim(hint)}")
            errs += 1
        else:
            hint = "shipping under experimental opt-in (may not work in-game)."
            print(f"  {_T_WARN} {_ST.bold(modname)}: content kind "
                  f"{_ST.accent(repr(kind))} is {_ST.warn(repr(conf))} — "
                  f"{_ST.dim(hint)}")
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
            print(f"  {_T_FAIL} {_ST.bold(modname)}: item content missing 'id'")
            errs += 1
            continue
        if not base:
            print(f"  {_T_FAIL} {_ST.bold(modname)}: item {_ST.accent(str(cid))}: "
                  f"missing 'base'")
            errs += 1
            continue
        found = cmd_items._find_item(str(base))
        if found is None:
            hint = "not a known vanilla item (falls back to legacy manifest)"
            print(f"  {_T_WARN} {_ST.bold(modname)}: item {_ST.accent(str(cid))}: "
                  f"base {_ST.accent(repr(base))} {_ST.dim(hint)}")
            warns += 1
            continue
        data = found[2].read_bytes()
        for vp in c.get("value_patches", []) or []:
            label, old = (vp[0], vp[1]) if isinstance(vp, list) else (
                vp.get("label"), vp.get("old"))
            try:
                cook.set_value_after_label(data, str(label), float(old), float(old))
            except (ValueError, TypeError) as e:
                print(f"  {_T_FAIL} {_ST.bold(modname)}: item {_ST.accent(str(cid))}: "
                      f"value_patch {_ST.accent(repr(label))}: {_ST.dim(str(e))}")
                errs += 1
        icon = c.get("icon")
        if icon and "\\" not in str(icon) and "/" not in str(icon) \
                and not str(icon).lower().endswith(".png"):
            if str(icon) not in cmd_items._icon_stems(None):
                hint = "not a known vanilla stem (try `rsmm items icons`)"
                print(f"  {_T_WARN} {_ST.bold(modname)}: item {_ST.accent(str(cid))}: "
                      f"icon {_ST.accent(repr(icon))} {_ST.dim(hint)}")
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
        hint = (f"— mods ship data, not code; move its logic into rsmm.sdk and "
                f"express the mod as [[content]]/[[patch]] "
                f"(sanctioned hooks: {sorted(allowed)})")
        print(f"  {_T_FAIL} {_ST.bold(modname)}: stray script "
              f"{_ST.accent(repr(rel))} {_ST.dim(hint)}")
        errs += 1
    return errs, 0


#: Events the loader always emits (dllmain lifecycle), independent of the
#: RE'd gameplay-event catalog in data/symbols.json.
_BUILTIN_EVENTS = {"setup", "ready", "tick", "exit"}

# Derived events: rsmm.lua watches cheap state each tick and republishes the
# TRANSITIONS, so a mod can say "when a run starts" instead of polling. They
# are emitted by the SDK, not by a symbol, so the symbol map never mentions
# them — without this the linter warned "handler will never fire" on every mod
# using the surface shipped in 0.4.19. Scraped from rsmm.lua rather than
# hardcoded so the two cannot drift.
_SDK_PUBLISH = re.compile(r"""_publish\(\s*['"]([a-z][a-z_]*:[a-z_]+)['"]""")
_SDK_PUBLISH_TERNARY = re.compile(
    r"""_publish\(\s*[^,()]*?\s+and\s+['"]([a-z][a-z_]*:[a-z_]+)['"]"""
    r"""\s+or\s+['"]([a-z][a-z_]*:[a-z_]+)['"]"""
)


def _sdk_derived_events() -> set[str]:
    """Event names rsmm.lua publishes itself (run:start, menu:enter, ...)."""
    lua = Path(__file__).resolve().parents[3] / "src" / "loader" / "lib" / "rsmm.lua"
    try:
        text = lua.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return set()
    out = set(_SDK_PUBLISH.findall(text))
    for a, b in _SDK_PUBLISH_TERNARY.findall(text):
        out.update((a, b))
    return out

_RE_ON = re.compile(r"""R\.on\(\s*['"]([^'"]+)['"]""")
_RE_ENGINE = re.compile(r"""R\.engine\.(?:call|resolve)\(\s*['"]([^'"]+)['"]""")

# A mod must never reach into raw memory or the engine by address. Those
# concerns live in the SDK (rsmm.lua + the symbol map); a mod consumes only the
# high-level R.* API. This catches (a) literal game virtual addresses
# (0x14xxxxxxx — the Ravenswatch.exe VA range) and (b) the low-level escape-hatch
# primitives, so a new capability is forced through the SDK rather than baked
# into a mod where it silently rots across game updates.
_RE_RAW_VA = re.compile(r"\b0x14[0-9a-fA-F]{7}\b")
_RE_LOWLEVEL = re.compile(
    r"""(?:\b_internal\b"""
    r"""|\.peek\(|\.poke\("""
    r"""|\.module_base\(|\.scratch\("""
    r"""|\.read_(?:u\d+|f\d+|cstr|f32|f64)\(|\.write_(?:u\d+|f\d+|f32|f64)\("""
    r"""|\.call_raw\(|\.engine\.resolve\()"""
)


def _engine_vocab() -> tuple[set[str], set[str]]:
    """(valid event names, valid R.engine.* symbol names) from the symbol map,
    plus built-in events. Empty symbol sets if the map can't be loaded."""
    events = set(_BUILTIN_EVENTS) | _sdk_derived_events()
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
    footgun the symbol map exists to prevent. Also *error* on raw memory
    addresses / low-level primitives: those belong in the SDK, not a mod."""
    events, callables = _engine_vocab()
    errs = 0
    warns = 0
    for f in sorted(entry.rglob("*.lua")):
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        rel = f.relative_to(entry).as_posix()
        for ln, line in enumerate(text.splitlines(), 1):
            code = line.split("--", 1)[0]  # ignore comments
            if _RE_RAW_VA.search(code):
                hint = ("— mods must not hardcode engine addresses; add a symbol "
                        "to data/symbols.json and reach it through the SDK (R.*)")
                print(f"  {_T_ERR}  {_ST.bold(modname)}: {_ST.accent(f'{rel}:{ln}')}: "
                      f"raw game address {_ST.dim(hint)}")
                errs += 1
            if _RE_LOWLEVEL.search(code):
                hint = ("(_internal/peek/poke/read_*/write_*/module_base/scratch/"
                        "call_raw/resolve) — wrap the capability in the SDK and "
                        "expose a high-level R.* API; mods consume only that")
                print(f"  {_T_ERR}  {_ST.bold(modname)}: {_ST.accent(f'{rel}:{ln}')}: "
                      f"low-level primitive {_ST.dim(hint)}")
                errs += 1
        for ev in _RE_ON.findall(text):
            # "*" is the wildcard channel (every event); "gameplay:<NAME>" is
            # the open-ended oCGameNamedEvent bus — the loader republishes
            # whatever the engine fires, so the name set isn't enumerable and
            # these must not warn.
            # "ui:press" is the native-UI button bridge (hook_ui.cpp,
            # RSMM_ENABLE_UI_HOOK) — loader-emitted, not in the symbol map.
            if ev == "*" or ev.startswith("gameplay:") or ev.startswith("ui:"):
                continue
            if ev not in events:
                hint = (f"— unknown event (known: {', '.join(sorted(events))}); "
                        f"handler will never fire")
                print(f"  {_T_WARN} {_ST.bold(modname)}: {_ST.accent(rel)}: "
                      f"R.on({ev!r}) {_ST.dim(hint)}")
                warns += 1
        if callables:
            for nm in _RE_ENGINE.findall(text):
                if nm not in callables:
                    hint = "— not a callable symbol (see `rsmm symbols list`)"
                    print(f"  {_T_WARN} {_ST.bold(modname)}: {_ST.accent(rel)}: "
                          f"R.engine call to {_ST.accent(repr(nm))} {_ST.dim(hint)}")
                    warns += 1
    return errs, warns


def main() -> int:
    ap = argparse.ArgumentParser(description="Validate mod manifests + assets")
    ap.add_argument("mod_id", nargs="?", default=None)
    args = ap.parse_args()

    if not MODS_DIR.is_dir():
        # mods/ is user-local and untracked (see .gitignore) — absent on a
        # fresh CI checkout. Nothing to lint is not a failure.
        if args.mod_id:
            print(_ST_ERR.err(f"no such mod: {args.mod_id}"), file=sys.stderr)
            return 1
        print(_ST.dim("mods/ not found — nothing to lint"))
        return 0

    candidates: list[Path] = []
    if args.mod_id:
        p = MODS_DIR / args.mod_id
        if not p.is_dir():
            print(_ST_ERR.err(f"no such mod: {args.mod_id}"), file=sys.stderr)
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
            print(f"\n{_ST.heading('dependency graph:')}")
            for it in issues:
                if it.severity == "error":
                    print(f"  {_T_ERROR} {_ST.accent(it.code)}: {it.message}")
                elif it.severity == "warn":
                    print(f"  {_T_WARN}  {_ST.accent(it.code)}: {it.message}")
        total_e += graph_e
        total_w += graph_w

    counted = _ST.bold(f"{len(candidates)} mod(s) linted")
    e_txt = f"{total_e} error(s)"
    w_txt = f"{total_w} warning(s)"
    e_s = _ST.err(e_txt) if total_e else _ST.ok(e_txt)
    w_s = _ST.warn(w_txt) if total_w else _ST.ok(w_txt)
    print(f"\n{counted}: {e_s}, {w_s}")
    return 1 if total_e else 0


if __name__ == "__main__":
    sys.exit(main())
