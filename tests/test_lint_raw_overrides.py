"""Raw `assets/` override validation in `rsmm lint`.

A raw override ships finished bytes that `apply` copies over a retail asset,
so nothing inspects the edit until the game does. These cover the three ways
that goes wrong silently: a no-op override, an edit to a shadowed value node,
and a length change that re-frames the container.

The vanilla corpus (`data/uncooked/`) is game-derived and gitignored, so every
test injects its own `vanilla_root` instead of reading from disk.
"""

import struct

from rsmm.cli.lint import _lint_raw_overrides

_BEGIN = b"\x11\x11\xbb\xaa"
_END = b"\x22\x22\xbb\xaa"
_ENT = "Thing.entity.ot.EntitySettingsResource.gen"


def _lstr(s: str) -> bytes:
    return struct.pack("<I", len(s)) + s.encode("ascii")


def _node(label: str, value: float, *, shadowed: bool = False) -> bytes:
    """One cooked value node: label, its `0e` override sub-section, then the
    f32 immediately before the closing END marker."""
    payload = b"\x01\xde\xad\xbe" if shadowed else b"\x00"
    return (_lstr(label)
            + _BEGIN + struct.pack("<I", 0x0e) + payload
            + _BEGIN + struct.pack("<I", 0x0f)
            + struct.pack("<f", value) + _END)


def _mod(tmp_path, name, blob):
    entry = tmp_path / "mod"
    (entry / "assets").mkdir(parents=True, exist_ok=True)
    (entry / "assets" / name).write_bytes(blob)
    return entry


def _vanilla(tmp_path, name, blob):
    root = tmp_path / "vanilla"
    root.mkdir(parents=True, exist_ok=True)
    (root / name).write_bytes(blob)
    return root


def test_identical_override_warns(tmp_path, capsys):
    blob = _node("Crit Chance Value", 0.1)
    entry = _mod(tmp_path, _ENT, blob)
    root = _vanilla(tmp_path, _ENT, blob)
    errs, warns = _lint_raw_overrides("M", entry, vanilla_root=root)
    assert (errs, warns) == (0, 1)
    assert "identical to vanilla" in capsys.readouterr().out


def test_live_value_edit_is_clean(tmp_path, capsys):
    entry = _mod(tmp_path, _ENT, _node("Crit Chance Value", 0.15))
    root = _vanilla(tmp_path, _ENT, _node("Crit Chance Value", 0.1))
    errs, warns = _lint_raw_overrides("M", entry, vanilla_root=root)
    assert (errs, warns) == (0, 0)
    # The change is still reported so the author sees what they shipped.
    assert "0.1 -> 0.15" in capsys.readouterr().out


def test_shadowed_value_edit_errors(tmp_path, capsys):
    entry = _mod(tmp_path, _ENT, _node("Damage Value", 0.5, shadowed=True))
    root = _vanilla(tmp_path, _ENT, _node("Damage Value", 0.2, shadowed=True))
    errs, warns = _lint_raw_overrides("M", entry, vanilla_root=root)
    assert errs == 1
    assert "shadowed" in capsys.readouterr().out


def test_length_change_warns(tmp_path, capsys):
    entry = _mod(tmp_path, _ENT, _node("Crit Chance Value", 0.15) + b"\x00\x00")
    root = _vanilla(tmp_path, _ENT, _node("Crit Chance Value", 0.1))
    errs, warns = _lint_raw_overrides("M", entry, vanilla_root=root)
    assert warns == 1
    assert "structural override" in capsys.readouterr().out


def test_new_asset_without_vanilla_twin_is_ignored(tmp_path):
    entry = _mod(tmp_path, _ENT, _node("Crit Chance Value", 0.15))
    root = tmp_path / "vanilla"
    root.mkdir()
    assert _lint_raw_overrides("M", entry, vanilla_root=root) == (0, 0)


def test_missing_corpus_is_not_a_failure(tmp_path, monkeypatch):
    """No `data/uncooked/` (fresh clone, frozen sidecar, worktree) => advisory
    checks skip rather than fail every mod."""
    monkeypatch.setattr("rsmm.cli.lint._vanilla_root", lambda: None)
    entry = _mod(tmp_path, _ENT, _node("Crit Chance Value", 0.15))
    assert _lint_raw_overrides("M", entry) == (0, 0)


def test_clearing_the_override_is_a_fix_not_an_error(tmp_path, capsys):
    """Un-shadowing is the documented way to make an inline value apply.

    Regression: the shadow flag was read off the *vanilla* node, so a mod that
    correctly cleared the `0e` override — `talent_values.clear_value_override`,
    the sanctioned fix — was reported as an error claiming its edit had no
    in-game effect. Exactly backwards, and nothing the author could do about
    it. Both `DamagePowerTweaks` and `PamsFixes` were failing CI on this.
    """
    entry = _mod(tmp_path, _ENT, _node("Damage Value", 0.1, shadowed=False))
    root = _vanilla(tmp_path, _ENT, _node("Damage Value", 0.2, shadowed=True))
    errs, _warns = _lint_raw_overrides("M", entry, vanilla_root=root)
    # Only the error matters here. Dropping the selector ref shortens the node,
    # so the structural-override warning also fires — legitimate, and a
    # separate concern from whether the edit takes effect.
    assert errs == 0
    out = capsys.readouterr().out
    assert "un-shadowed" in out
    assert "0.2 -> 0.1" in out


def test_newly_shadowing_a_live_value_warns(tmp_path, capsys):
    """The opposite direction: a mod that switches a value to a selector has
    silently disconnected that number, even though it edited nothing else."""
    entry = _mod(tmp_path, _ENT, _node("Crit Chance Value", 0.1, shadowed=True))
    root = _vanilla(tmp_path, _ENT, _node("Crit Chance Value", 0.1, shadowed=False))
    errs, warns = _lint_raw_overrides("M", entry, vanilla_root=root)
    assert errs == 0 and warns >= 1
    assert "newly shadowed" in capsys.readouterr().out
