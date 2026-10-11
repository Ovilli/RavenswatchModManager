"""Every content kind must build the same bytes without the `data/uncooked` mirror.

The mirror is gitignored and never bundled, so a player's machine does not have
it. Until 2026-09-23 most kinds read it directly: moved aside, 34 of the 42
content blocks in the repo's own mods failed, and the custom magic-item clone
silently fell back to a legacy manifest instead of cooking. `rsmm.engine.corpus`
now answers every read from the mirror OR the game install.

Two guards:

* a static one (runs everywhere, CI included): no kind module may build a
  `DATA_DIR / "uncooked"` path — that is how the bug was written each time;
* a dynamic one (needs a game install, so it skips on CI): each kind emits
  byte-identical files from the mirror and from the install alone.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

from rsmm.engine import corpus
from rsmm.sdk.content import ContentRegistry

_KINDS_DIR = Path(__file__).resolve().parents[1] / "src" / "rsmm" / "sdk" / "kinds"
_MIRROR_PATH = re.compile(r"""DATA_DIR\s*/\s*["']uncooked["']""")

#: Kind modules allowed ONE mirror path, and why. Each use must have an
#: install fallback next to it.
_ALLOWED = {
    # Derived files with no install twin: mirrored GLB geometry (decoded from
    # the cooked `.Geometry.gen` when absent) and texture PNGs (probed next to
    # `corpus.install_path` for the cooked `.Texture.dxt`). Also the
    # corpus-cache key of last resort.
    "poi.py": 1,
}


def test_no_kind_reads_the_mirror_directly():
    offenders = {}
    for p in sorted(_KINDS_DIR.rglob("*.py")):
        n = len(_MIRROR_PATH.findall(p.read_text(encoding="utf-8")))
        if n > _ALLOWED.get(p.name, 0):
            offenders[str(p.relative_to(_KINDS_DIR))] = n
    assert not offenders, (
        f"{offenders}: read vanilla bytes through rsmm.engine.corpus "
        f"(corpus.read / corpus.files / corpus.stems), never a data/uncooked path "
        f"— a player's machine has no mirror")


#: One representative block per kind that reads the corpus, with field values
#: taken from mods that have been applied for real.
_BLOCKS = [
    ("item", "FrostOrb", {"base": "Orb_Grants_Strength", "name": "Frost Orb",
                          "rarity": "Epic"}),
    ("item", "NoArmor", {"mode": "ban", "items": ["Armor_Per_Object"]}),
    ("enemy", "FrostGhoul", {"base": "Sling_Ghoul", "add_flags": ["Elite"]}),
    ("hero", "IceHero", {"base": "Aladdin"}),
    ("map", "DarkRemix", {"base": "Dark_Hills", "chapter": 0}),
    ("boss", "CrabDen", {"base": "Boss_Marsh_Ghoul", "becomes": "Boss_Crab"}),
    ("modifier", "MoreXp2", {"base": "MoreExperience", "name": "More XP",
                             "description": "d"}),
    ("tilegen", "Busy", {"chapter": "DarkHills", "quotas": {"Wishing_Well": 2}}),
    ("game_mode", "All_Chapters", {"base": "All_Chapters", "chapters": [1, 0]}),
    ("reward", "Astro", {"base": "Camp_Rewards_Dark_Hills_Update5",
                         "ban": ["DreamCrystal"], "counts": {"2": [3, 3]}}),
    ("melody", "Heal", {"base": "Fully_Heal", "effect": "Reveal_Map"}),
    ("skill", "Meteor", {"hero": "Aladdin", "source": "Attack Dive",
                         "name": "Meteor", "description": "d"}),
    ("talent", "IceClone", {"hero": "Snow_Queen", "file": "Hero_Snow_Queen_Ice_Clone.entity",
                            "value_patches": [{"label": "Explosion Damage",
                                               "old": 10.0, "new": 8.0}]}),
]


def _emit(out: Path, kind: str, cid: str, fields: dict) -> dict[str, str]:
    cr = ContentRegistry(mod_id="CorpusFallback", experimental=True)
    cr.register(kind, id=cid, **fields)
    paths = cr.emit(out)
    return {str(p.relative_to(out)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in paths if p.is_file()}


@pytest.mark.slow
@pytest.mark.parametrize("kind, cid, fields", _BLOCKS, ids=[f"{k}-{c}" for k, c, _ in _BLOCKS])
def test_kind_builds_the_same_bytes_from_the_install(tmp_path, monkeypatch, kind, cid, fields):
    if corpus.source() != "mirror":
        pytest.skip("needs the data/uncooked mirror to compare against")
    if corpus.cooking_dir() is None:
        pytest.skip("needs a game install")
    from_mirror = _emit(tmp_path / "mirror", kind, cid, fields)
    assert from_mirror, "emitted nothing even with the mirror"

    monkeypatch.setattr(corpus, "UNCOOKED", Path("/nonexistent/uncooked"))
    from rsmm.engine import enemy_pools as EP
    monkeypatch.setattr(EP, "UNCOOKED", Path("/nonexistent/uncooked"))
    monkeypatch.setattr(EP, "ENEMY_DIR", Path("/nonexistent/uncooked/Definitions/Enemies"))
    monkeypatch.setattr(EP, "OT_DIR", Path("/nonexistent/uncooked/Ot"))
    assert corpus.source() == "install"
    from_install = _emit(tmp_path / "install", kind, cid, fields)
    assert from_install == from_mirror


#: Commands and registries authors use on a normal install. `rsmm talents`,
#: `rsmm enemies`, the console snapshot and the magic-item registry all read
#: only the mirror until 2026-09-23 — so they listed nothing for a player, and
#: the magic-item registry was empty everywhere (it read `.gen.txt` dumps nothing
#: writes by default).
_BROWSERS = [
    "src/rsmm/cli/cmd_talents.py",
    "src/rsmm/cli/cmd_enemies.py",
    "src/rsmm/cli/cmd_items.py",
    "src/rsmm/cli/cmd_schema.py",
    "src/rsmm/cli/console_cmd.py",
    "src/rsmm/engine/magic_items.py",
]
_ANY_MIRROR_PATH = re.compile(r"""["']uncooked["']""")


@pytest.mark.parametrize("rel", _BROWSERS)
def test_browsing_commands_do_not_read_the_mirror(rel):
    src = (Path(__file__).resolve().parents[1] / rel).read_text(encoding="utf-8")
    code = "\n".join(line for line in src.splitlines()
                     if not line.lstrip().startswith("#"))
    assert not _ANY_MIRROR_PATH.search(code), (
        f"{rel} builds a data/uncooked path — read through rsmm.engine.corpus")
