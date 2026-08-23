"""A rebuild must read the PRISTINE resource manifest, never a modded one.

`rsmm apply` appends a UsedRscList record per new asset, so rebuilding while
mods are applied bakes their invented names into data/asset_map.json as if the
game shipped them. That is not cosmetic: `is_vanilla_encoded` is asset_map
backed, so the next apply REFUSES to plant those very files ("the game ships
this file but it is not there, and no backup exists") and the mod silently
cannot install. The map is a tracked artifact, so the bad data ships too —
measured 2026-08-23, 100 phantom rows from two dev mods, already committed.
"""

from __future__ import annotations

import json

from rsmm.engine import find_iyg

# Three lines per record, matching the manifest's grouping.
_VANILLA = ["Nqhdzdidrzv", "Qdlqv", "3N"]
_MOD_ADDED = ["Ngum_Adllv!xrn-idlq", "Qdlqv!xrn-idlq", "3N!xrn"]


def _manifest(path, lines):
    path.write_text("\n".join([str(len(lines))] + lines) + "\n", encoding="utf-8")


def _rebuild(tmp_path, monkeypatch, live_lines, pristine_lines):
    live = tmp_path / "UsedRscList.ot"
    _manifest(live, live_lines)
    if pristine_lines is not None:
        _manifest(live.with_name(live.name + find_iyg.BACKUP_SUFFIX), pristine_lines)
    out_json = tmp_path / "asset_map.json"
    monkeypatch.setattr(find_iyg, "ASSET_MAP_JSON", out_json)
    monkeypatch.setattr(find_iyg, "ASSET_MAP_CSV", tmp_path / "asset_map.csv")
    assert find_iyg.main(str(live)) == 0
    return json.loads(out_json.read_text(encoding="utf-8"))


def test_rebuild_prefers_the_pristine_backup(tmp_path, monkeypatch, capsys):
    """With mod records live, the backup is the source — and it says so."""
    mapping = _rebuild(tmp_path, monkeypatch,
                       live_lines=_VANILLA + _MOD_ADDED,
                       pristine_lines=_VANILLA)

    assert len(mapping) == len(_VANILLA)
    for enc in _MOD_ADDED:
        assert enc not in mapping, "a mod-added record reached the asset map"
    assert "custom record(s) are registered" in capsys.readouterr().out


def test_rebuild_uses_the_live_manifest_when_it_is_pristine(tmp_path, monkeypatch):
    """No custom records: the live file IS the pristine one, backup or not."""
    mapping = _rebuild(tmp_path, monkeypatch,
                       live_lines=_VANILLA, pristine_lines=_VANILLA)
    assert len(mapping) == len(_VANILLA)

    mapping = _rebuild(tmp_path, monkeypatch,
                       live_lines=_VANILLA, pristine_lines=None)
    assert len(mapping) == len(_VANILLA)
