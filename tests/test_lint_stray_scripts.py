"""Guardrail: a mod ships data, not code.

``rsmm lint`` must fail any ``*.py`` in a mod folder that isn't a
sanctioned lifecycle hook, so a one-off discovery script can never be
shipped as the deliverable instead of graduating into ``rsmm.sdk``.
"""

from __future__ import annotations

from rsmm.cli import lint


def _mod(tmp_path, name="DemoMod"):
    d = tmp_path / name
    (d / "assets").mkdir(parents=True)
    (d / "manifest.toml").write_text('[mod]\nid = "DemoMod"\n')
    return d


def test_clean_mod_has_no_stray_scripts(tmp_path):
    d = _mod(tmp_path)
    (d / "assets" / "thing.gen").write_bytes(b"\x00\x01")
    assert lint._lint_stray_scripts("DemoMod", d) == (0, 0)


def test_sanctioned_hook_is_allowed(tmp_path):
    d = _mod(tmp_path)
    (d / "on_disable.py").write_text("# lifecycle hook\n")
    assert lint._lint_stray_scripts("DemoMod", d) == (0, 0)


def test_stray_script_fails(tmp_path, capsys):
    d = _mod(tmp_path)
    (d / "cook_hack.py").write_text("print('hand-rolled byte poke')\n")
    errs, warns = lint._lint_stray_scripts("DemoMod", d)
    assert errs == 1
    assert warns == 0
    out = capsys.readouterr().out
    assert "stray script" in out
    assert "cook_hack.py" in out


def test_stray_script_in_subdir_fails(tmp_path):
    d = _mod(tmp_path)
    (d / "tools").mkdir()
    (d / "tools" / "mine_offsets.py").write_text("x = 1\n")
    errs, _ = lint._lint_stray_scripts("DemoMod", d)
    assert errs == 1


def test_sanctioned_set_matches_apply_pipeline():
    # If apply_mods grows a new hook, the allowlist must track it or the
    # new hook would be rejected as a stray script.
    from rsmm.cli.apply_mods import DEACTIVATION_SCRIPT_NAME

    assert DEACTIVATION_SCRIPT_NAME in lint._sanctioned_scripts()
