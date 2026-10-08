"""Forgiving names: every mod-taking command resolves an id the same way, and
a typo'd subcommand gets one line with a suggestion instead of the listing."""

from __future__ import annotations

import pytest

from rsmm.cli import _dispatch as D
from rsmm.cli import cmd_mods, lint
from rsmm.cli._suggest import UnknownMod, did_you_mean, resolve_mod


@pytest.fixture()
def mods(tmp_path, monkeypatch):
    d = tmp_path / "mods"
    for name in ("MyMod", "HyperAggro", "_merged"):
        (d / name).mkdir(parents=True)
        (d / name / "manifest.toml").write_text(
            f'[mod]\nid = "{name}"\nversion = "0.1.0"\nenabled = true\n',
            encoding="utf-8")
    monkeypatch.setenv("RSMM_MODS_DIR", str(d))
    return d


def test_exact_and_case_insensitive_names_resolve(mods):
    assert resolve_mod("MyMod", mods) == "MyMod"
    assert resolve_mod("mymod", mods) == "MyMod"
    assert resolve_mod("HYPERAGGRO", mods) == "HyperAggro"


def test_tab_completed_and_path_spellings_resolve(mods, monkeypatch):
    assert resolve_mod("MyMod/", mods) == "MyMod"
    assert resolve_mod("MyMod\\", mods) == "MyMod"
    assert resolve_mod(str(mods / "MyMod"), mods) == "MyMod"
    monkeypatch.chdir(mods.parent)
    assert resolve_mod("mods/MyMod/", mods) == "MyMod"


def test_underscored_folders_resolve_only_when_named_exactly(mods):
    assert resolve_mod("_merged", mods) == "_merged"
    with pytest.raises(UnknownMod) as e:
        resolve_mod("merged", mods)
    assert "_merged" not in str(e.value), "apply's own output is never offered"


def test_a_typo_gets_a_suggestion(mods):
    with pytest.raises(UnknownMod, match=r"did you mean MyMod\?"):
        resolve_mod("MyMood", mods)


def test_nothing_close_lists_what_is_installed(mods):
    with pytest.raises(UnknownMod, match=r"installed: HyperAggro, MyMod\)"):
        resolve_mod("zzz", mods)


def test_an_empty_mods_dir_says_how_to_start(tmp_path):
    with pytest.raises(UnknownMod, match="rsmm new"):
        resolve_mod("Anything", tmp_path)


@pytest.mark.parametrize("arg", ["..", "../mods", "MyMod/..", "mods/.."])
def test_paths_outside_mods_never_resolve(mods, monkeypatch, arg):
    monkeypatch.chdir(mods.parent)
    with pytest.raises(UnknownMod):
        resolve_mod(arg, mods)


def test_two_folders_differing_only_in_case_need_the_exact_name(tmp_path):
    for name in ("Mod", "MOD"):
        try:
            (tmp_path / name).mkdir()
        except FileExistsError:
            pytest.skip("case-insensitive filesystem")
    assert resolve_mod("Mod", tmp_path) == "Mod"
    with pytest.raises(UnknownMod):
        resolve_mod("mod", tmp_path)


def test_did_you_mean_lists_several_close_choices():
    assert did_you_mean("lis", ["list", "lint", "log"]).startswith(" (did you mean ")
    assert did_you_mean("zzz", ["list"]) == ""


def test_unknown_subcommand_is_one_line_with_a_suggestion(capsys):
    assert D.main(["aply"]) == 2
    err = capsys.readouterr().err
    assert "unknown subcommand: aply (did you mean apply?)" in err
    assert len(err.strip().splitlines()) == 2, "no full listing dumped"


def test_enable_forgives_case_and_suggests_on_typos(mods, capsys):
    (mods / "MyMod" / "manifest.toml").write_text(
        '[mod]\nid = "MyMod"\nenabled = false\n', encoding="utf-8")
    assert cmd_mods.main(["enable", "mymod", "--no-apply",
                          "--mods-dir", str(mods)]) == 0
    assert "enabled = true" in (mods / "MyMod" / "manifest.toml").read_text()
    assert cmd_mods.main(["disable", "hyperagro", "--no-apply",
                          "--mods-dir", str(mods)]) == 2
    assert "did you mean HyperAggro?" in capsys.readouterr().err


def test_lint_takes_a_mis_cased_id(mods, monkeypatch, capsys):
    monkeypatch.setattr(lint, "MODS_DIR", mods)
    monkeypatch.setattr("sys.argv", ["lint", "mymod/"])
    lint.main()
    assert "MyMod" in capsys.readouterr().out
    monkeypatch.setattr("sys.argv", ["lint", "MyMood"])
    assert lint.main() == 1
    assert "did you mean MyMod?" in capsys.readouterr().err
