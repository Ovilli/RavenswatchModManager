"""Every ENABLED local mod's content must actually emit.

`rsmm lint` reads a manifest; it does not run the emitters. So a value the
emitter refuses — a `copies` over MAX_COPIES, a swaps target that is not
placeable, a base tile that does not exist — passes lint clean and only fails
at `rsmm apply`. That is the expensive place for it to fail: a failed content
emit deliberately removes the mod's previously planted assets, so the install
goes from working to empty, and the next launch reports the mod doing nothing.

That is not hypothetical. `copies = 20` against a MAX_COPIES of 16 shipped to a
playtest, wiped 24 planted overrides down to 2, and cost a full run to notice —
lint was green the whole time.

Skipped when `mods/` is absent (it is untracked), same as the other local-mod
suites.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
MODS = REPO / "mods"


def _enabled_mod_dirs() -> list[Path]:
    import tomllib
    out = []
    for m in sorted(MODS.glob("*/manifest.toml")):
        try:
            data = tomllib.loads(m.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            continue
        if (data.get("mod") or {}).get("enabled"):
            out.append(m.parent)
    return out


def test_enabled_local_mods_emit(tmp_path):
    if not MODS.is_dir():
        pytest.skip("mods/ is untracked and absent in this checkout")
    mods = _enabled_mod_dirs()
    if not mods:
        pytest.skip("no enabled local mods to emit")

    from rsmm.sdk.content import ContentDef, ContentError
    from rsmm.sdk.kinds import poi as P

    failures: list[str] = []
    for mod_dir in mods:
        try:
            blocks = P.discover(mod_dir)
        except ContentError as e:
            failures.append(f"{mod_dir.name}: discover: {e}")
            continue
        for b in blocks:
            defn = ContentDef(
                kind="poi", id=b["id"],
                fields={k: v for k, v in b.items() if k not in ("kind", "id")},
            )
            # `out_dir` is the mod's `assets/` directory: the emitter resolves
            # source art (model.glb, icon.png) through its PARENT, so the mod
            # folder has to be copied whole and emitted into a sibling
            # `assets/`. Pointing out_dir at a bare tmp path makes every
            # mod-relative source lookup miss and reports it as the mod's bug.
            staged = tmp_path / mod_dir.name
            if not staged.exists():
                shutil.copytree(mod_dir, staged,
                                ignore=shutil.ignore_patterns("assets"))
            out = staged / "assets"
            out.mkdir(parents=True, exist_ok=True)
            try:
                written = P.emit(mod_dir.name, defn, out)
            except ContentError as e:
                failures.append(f"{mod_dir.name}/{b['id']}: {e}")
                continue
            # An emit that writes nothing is a silent no-op: the mod applies,
            # reports success, and plants no tile.
            if not written:
                failures.append(f"{mod_dir.name}/{b['id']}: emitted no files")

    assert not failures, (
        "enabled local mod(s) fail to emit — `rsmm apply` would fail and REMOVE "
        "their already-planted assets:\n  " + "\n  ".join(failures)
    )
