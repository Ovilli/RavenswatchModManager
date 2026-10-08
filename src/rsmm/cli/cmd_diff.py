"""`rsmm diff <mod>` — what applying one mod changes in the game.

Read-only. For every file the mod ships it answers three questions an author
otherwise learns from a playtest:

  * does it REPLACE a game file, ADD a new one, or get SKIPPED (no asset_map
    entry and no sibling to anchor a new path)?
  * does another enabled mod write the same file — and if so, is it merged
    (text banks, tile pools, resource caches, alias tables) or does one mod's
    copy silently lose?
  * when the game is found: is it installed, out of date, or not applied yet?

`[[patch]]` blocks are listed with any other mod that sets the same field, and
which one wins under (load_order, id). Resolution goes through the same
helpers `rsmm apply` uses (`resolve_special`, `synthesize_encoded`, the
additive-merge predicates), so this view cannot disagree with the real plan.

See STRATEGY §7 ("First-class debugging").
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from rsmm.cli import _term

#: Asset families every writer APPENDS to; `plan_apply` merges them rather
#: than letting the last mod win. Mirrors the `mergers` table there.
_MERGED_FAMILIES = (
    ("is_text_bank", "text bank"),
    ("is_map_def", "tile pool"),
    ("is_rsc_cache", "resource cache"),
    ("is_app_settings", "alias table"),
)

#: Entries shown per section before `--all` is needed. A custom hero ships
#: hundreds of files; the conflicts are what matter and those always print.
_SHOW = 15

_REPLACE, _ADD, _SKIP = "replace", "add", "skip"


@dataclass
class FileChange:
    decoded: str
    action: str                       # replace | add | skip
    encoded: str | None = None
    #: Other enabled mods writing the same target, in apply order.
    others: list[str] = field(default_factory=list)
    #: "text bank" etc. when the target is merged across writers, else "".
    merged_as: str = ""
    #: The mod whose copy lands, for an unmerged shared target.
    winner: str = ""
    #: installed | outdated | pending | owned:<mod> | "" (game not found)
    status: str = ""


@dataclass
class PatchChange:
    kind: str
    key: str
    value: object
    others: dict[str, object] = field(default_factory=dict)
    winner: str = ""


@dataclass
class DiffReport:
    mod_id: str
    name: str
    version: str
    enabled: bool
    files: list[FileChange]
    patches: list[PatchChange]
    content_kinds: list[str]
    content_emitted: bool
    game_found: bool

    def to_json(self) -> dict:
        return {
            "mod": self.mod_id, "name": self.name, "version": self.version,
            "enabled": self.enabled, "game_found": self.game_found,
            "files": [vars(f) for f in self.files],
            "patches": [vars(p) for p in self.patches],
            "content": {"kinds": self.content_kinds,
                        "emitted": self.content_emitted},
        }


def _merged_family(decoded: str) -> str:
    from rsmm.cli import apply_mods as A

    for pred, label in _MERGED_FAMILIES:
        if getattr(A, pred)(decoded):
            return label
    return ""


def _resolve(decoded: str, dec2enc: dict[str, str],
             game_dir: Path | None = None) -> tuple[str, str | None]:
    """(action, encoded) exactly as `plan_apply` would decide it."""
    from rsmm.cli import apply_mods as A

    enc = dec2enc.get(decoded) or A.resolve_special(decoded, dec2enc)
    if enc and enc.startswith(A.ROOT_PREFIX):
        # A top-level install file (`_root/...`) is outside the cooked
        # manifest, so only the install itself can say whether the game ships
        # it. Without one, assume an override: every `_root` asset the SDK
        # emits today (ApplicationSettings.ot, ...) is a shipped file.
        if game_dir is None:
            return _REPLACE, enc
        dest = A.encoded_to_dest(enc, game_dir / A.COOKING_REL, game_dir)
        bak = dest.parent / (dest.name + A.BACKUP_SUFFIX)
        return (_REPLACE if dest.exists() or bak.exists() else _ADD), enc
    if enc:
        return _REPLACE if A.is_vanilla_encoded(enc) else _ADD, enc
    enc = A.synthesize_encoded(decoded, dec2enc)
    return (_ADD, enc) if enc else (_SKIP, None)


def _install_status(enc: str, src: Path, mod_id: str, active: dict) -> str:
    from rsmm.cli import apply_mods as A
    from rsmm.engine import cook_cache

    cur = active.get(enc)
    if not isinstance(cur, dict):
        cur = None
    if not cur:
        return "pending"
    owner = cur.get("mod", "")
    if owner != mod_id:
        return f"owned:{owner}"
    # A source-format input (.gltf, .png for a texture, ...) is recorded by
    # the hash of its COOKED output, which only the cook cache knows.
    if cook_cache.is_source(src):
        return "installed"
    return "installed" if cur.get("src_sha256") == A.sha256(src) else "outdated"


def _patch_keys(kind: str, data: dict) -> list[tuple[str, object]]:
    """(key, value) per field a `[[patch]]` block sets — the unit two mods can
    collide on. Same keying as `doctor.check_patch_conflicts`."""
    from rsmm.cli.merge import DEFAULT_OT_FILE

    if kind == "stat":
        name = str(data.get("name", "")).lower()
        return [(f"{name}.{k}", v) for k, v in data.items() if k != "name"]
    if kind == "texture":
        return [(str(data.get("target", "")).replace("\\", "/"), data.get("donor"))]
    if kind == "ot":
        f = str(data.get("file") or DEFAULT_OT_FILE).replace("\\", "/")
        sel = f"{data.get('selector_field', '')}={data.get('selector', '')}"
        return [(f"{f} [{sel}].{data.get('field', '')}", data.get("value"))]
    return [("", data)]


def read_active(cooking: Path) -> dict | None:
    """The install's `active` override map, or None if there is none to read.

    Deliberately not `apply_mods.State`: that quarantines (renames) a corrupt
    state file, and `diff` promises to touch nothing."""
    from rsmm.cli.apply_mods import STATE_FILE_NAME

    path = cooking / STATE_FILE_NAME
    if not path.is_file():
        return {}
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    active = raw.get("active") if isinstance(raw, dict) else None
    return active if isinstance(active, dict) else None


def build_report(mod, mods: list, dec2enc: dict[str, str],
                 active: dict | None = None,
                 game_dir: Path | None = None) -> DiffReport:
    """Everything `rsmm diff` prints, as data. `mods` is every discovered mod
    in apply order (the order `plan_apply` sees them); `active` is the
    install's override map (`read_active`), or None when it is unknown."""
    from rsmm.cli.merge import _ranked, collect_patches

    # Who else writes each target. Enabled mods only — a disabled one installs
    # nothing — but the inspected mod is resolved even when it is disabled, so
    # an author can check a mod before switching it on.
    writers: dict[str, list[str]] = {}
    for other in mods:
        if other.root == mod.root or not other.enabled:
            continue
        for _src, decoded in other.files():
            _action, enc = _resolve(decoded, dec2enc, game_dir)
            if enc:
                writers.setdefault(enc, []).append(other.id)

    order = [m.id for m in mods]
    files: list[FileChange] = []
    for src, decoded in sorted(mod.files(), key=lambda f: f[1]):
        action, enc = _resolve(decoded, dec2enc, game_dir)
        fc = FileChange(decoded, action, enc)
        if enc:
            fc.others = writers.get(enc, [])
            if fc.others:
                fc.merged_as = _merged_family(decoded)
                if not fc.merged_as:
                    # plan_apply keeps writers[-1]: the last in discovery order.
                    ids = sorted({mod.id, *fc.others}, key=order.index)
                    fc.winner = ids[-1]
            if active is not None:
                fc.status = _install_status(enc, src, mod.id, active)
        files.append(fc)

    patches: list[PatchChange] = []
    every = _ranked(collect_patches())
    # collect_patches skips disabled mods; read the inspected one directly so
    # a disabled mod still shows what it would patch.
    own = [p for p in every if p.mod_id == mod.id]
    if not own and not mod.enabled:
        from rsmm.cli.merge import _Patch, _toml_load

        tbl = _toml_load(mod.root / "manifest.toml")
        lo = int(tbl.get("mod", {}).get("load_order", 100))
        for p in tbl.get("patch", []) or []:
            if p.get("kind"):
                own.append(_Patch(mod.id, lo, p["kind"],
                                  {k: v for k, v in p.items() if k != "kind"}))
        every = _ranked(every + own)
    for p in own:
        for key, value in _patch_keys(p.kind, p.data):
            pc = PatchChange(p.kind, key, value)
            for q in every:
                if q.mod_id == mod.id or q.kind != p.kind:
                    continue
                for qkey, qval in _patch_keys(q.kind, q.data):
                    # Two mods setting the same value agree; only a different
                    # value makes one of them lose (as `doctor` counts it).
                    if qkey == key and repr(qval) != repr(value):
                        pc.others[q.mod_id] = qval
            if pc.others:
                pc.winner = [q.mod_id for q in every
                             if q.mod_id == mod.id or q.mod_id in pc.others][-1]
            patches.append(pc)

    kinds = sorted({str(b.get("kind", "?")) for b in mod.content_blocks})
    return DiffReport(
        mod_id=mod.id, name=mod.name, version=mod.version, enabled=mod.enabled,
        files=files, patches=patches, content_kinds=kinds,
        content_emitted=(mod.root / ".rsmm_emitted.json").is_file(),
        game_found=active is not None,
    )


# --- rendering ----------------------------------------------------------------

_GLYPH = {_REPLACE: "~", _ADD: "+", _SKIP: "?"}
_TITLE = {
    _REPLACE: "replaces {n} game file(s)",
    _ADD: "adds {n} new file(s)",
    _SKIP: "skips {n} file(s) — no asset_map entry and no sibling to anchor a path",
}


def _file_note(fc: FileChange, mod_id: str, st: _term.Style) -> str:
    bits: list[str] = []
    if fc.others and fc.merged_as:
        bits.append(st.ok(f"merged ({fc.merged_as}) with {', '.join(fc.others)}"))
    elif fc.others and fc.winner == mod_id:
        bits.append(st.warn(f"conflict: overrides {', '.join(fc.others)}"))
    elif fc.others:
        bits.append(st.err(f"conflict: LOST to {fc.winner}"))
    if fc.status == "outdated":
        bits.append(st.warn("installed copy is out of date"))
    elif fc.status.startswith("owned:"):
        bits.append(st.dim(f"currently installed by {fc.status[6:]}"))
    return ("  " + st.dim(" · ").join(bits)) if bits else ""


def render(rep: DiffReport, show_all: bool = False) -> str:
    st = _term.Style()
    out: list[str] = []
    state = st.ok("enabled") if rep.enabled else st.warn("disabled")
    out.append(f"{st.bold(rep.mod_id)}  {st.dim(f'{rep.name} {rep.version}')}"
               f"{st.dim(' · ')}{state}")
    if not rep.enabled:
        out.append(st.dim("  disabled: `rsmm apply` installs none of this "
                          f"until `rsmm enable {rep.mod_id}`"))

    for action in (_REPLACE, _ADD, _SKIP):
        group = [f for f in rep.files if f.action == action]
        if not group:
            continue
        out.append("")
        out.append("  " + st.bold(_TITLE[action].format(n=len(group))))
        # Shared targets always print; the rest is capped unless --all.
        flagged = [f for f in group if f.others or f.status == "outdated"]
        plain = [f for f in group if f not in flagged]
        shown = flagged + (plain if show_all else plain[:max(0, _SHOW - len(flagged))])
        for fc in sorted(shown, key=lambda f: f.decoded):
            out.append(f"    {_GLYPH[action]} {fc.decoded}{_file_note(fc, rep.mod_id, st)}")
        hidden = len(group) - len(shown)
        if hidden:
            out.append(st.dim(f"    … {hidden} more (--all to list every file)"))

    if rep.patches:
        out.append("")
        out.append("  " + st.bold(f"patches {len(rep.patches)} field(s)")
                   + st.dim("  (composed into mods/_merged at apply)"))
        for pc in rep.patches:
            note = ""
            if pc.others:
                rivals = ", ".join(f"{m}={v!r}" for m, v in pc.others.items())
                note = "  " + (st.warn(f"also set by {rivals}; this mod wins")
                               if pc.winner == rep.mod_id
                               else st.err(f"also set by {rivals}; {pc.winner} wins"))
            out.append(f"    {pc.kind:<7} {pc.key} = {pc.value!r}{note}")

    if rep.content_kinds:
        out.append("")
        when = ("files from the last apply are included above" if rep.content_emitted
                else "not emitted yet — `rsmm apply --dry-run` emits them")
        out.append("  " + st.bold("content ") + ", ".join(rep.content_kinds)
                   + st.dim(f"  ({when})"))

    if not (rep.files or rep.patches or rep.content_kinds):
        out.append("")
        out.append(st.dim("  ships no assets, patches or content: applying it "
                          "changes no game file (Lua-only mods run from the loader)"))

    out.append("")
    out.append("  " + _summary(rep, st))
    return "\n".join(out)


def _summary(rep: DiffReport, st: _term.Style) -> str:
    n = {a: sum(f.action == a for f in rep.files) for a in (_REPLACE, _ADD, _SKIP)}
    parts = [f"{n[_REPLACE]} replaced", f"{n[_ADD]} added"]
    if n[_SKIP]:
        parts.append(st.warn(f"{n[_SKIP]} skipped"))
    lost = sum(1 for f in rep.files if f.winner and f.winner != rep.mod_id)
    lost += sum(1 for p in rep.patches if p.winner and p.winner != rep.mod_id)
    if lost:
        parts.append(st.err(f"{lost} lost to another mod"))
    if rep.game_found:
        inst = sum(f.status == "installed" for f in rep.files)
        stale = sum(f.status == "outdated" for f in rep.files)
        todo = sum(f.status == "pending" for f in rep.files)
        parts.append(f"{inst} installed")
        if stale or todo:
            parts.append(st.warn(f"{stale + todo} need `rsmm apply`"))
    else:
        parts.append(st.dim("install status unknown (game not found)"))
    return st.dim(" · ").join(parts)


def _find(mods: list, ident: str):
    for m in mods:
        if ident in (m.id, m.root.name):
            return m
    return None


def main(argv: list[str] | None = None) -> int:
    from rsmm.cli import apply_mods as A
    from rsmm.engine.paths import COOKING_REL
    from rsmm.engine.paths import REPO_ROOT as REPO_DIR

    ap = argparse.ArgumentParser(
        prog="rsmm diff",
        description="Show which game files applying one mod would change, "
                    "and where it overlaps other enabled mods. Read-only.")
    ap.add_argument("mod", help="mod id (or its folder name under mods/)")
    ap.add_argument("--all", action="store_true",
                    help="list every file, not just the first few per section")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--game-dir", type=Path, default=None,
                    help="Ravenswatch install (autodetected; only needed for "
                         "install status)")
    args = ap.parse_args(argv)

    if not A._ensure_asset_map():
        return 1
    mods = A.discover_mods(REPO_DIR)
    mod = _find(mods, args.mod)
    if mod is None:
        known = ", ".join(m.id for m in mods) or f"none in {A.MODS_DIR}"
        print(f"no mod '{args.mod}' (known: {known})", file=sys.stderr)
        return 1

    active = None
    game_dir = args.game_dir or A.find_game_dir()
    if game_dir and (game_dir / COOKING_REL).is_dir():
        active = read_active(game_dir / COOKING_REL)
        if active is None:
            print("  [warn] the install's state file is unreadable; "
                  "run `rsmm doctor`", file=sys.stderr)
    else:
        game_dir = None

    rep = build_report(mod, mods, A.load_asset_map(REPO_DIR), active, game_dir)
    if args.json:
        print(json.dumps(rep.to_json(), indent=2, default=str))
    else:
        print(render(rep, show_all=args.all))
    return 0


if __name__ == "__main__":
    sys.exit(main())
