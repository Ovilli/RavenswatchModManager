"""`rsmm lint` rejects manifest keys nothing reads, and stat/texture patches
that would do nothing.

Every case here used to lint clean and install a mod that silently had no
effect. The asset map is stubbed so the test needs no game install.
"""

from __future__ import annotations

import pytest

from rsmm.cli import lint

_MAP = {
    "GlobalValues/Common_Settings/Bleed_Duration_Value.globalvalue.ot."
    "GlobalEntityValueSettings.gen": "a",
    "Definitions/Camps/Easy.enemycampdifficultydef.ot."
    "DtEnemyCampDifficultyDefinition.gen": "b",
    "Ui/A.png.Texture.dxt": "c",
    "Ui/B.png.Texture.dxt": "d",
}


@pytest.fixture(autouse=True)
def _stub_asset_map(monkeypatch):
    monkeypatch.setattr(lint, "decoded_to_encoded", lambda: _MAP)


def _lint(tmp_path, body: str) -> int:
    root = tmp_path / "M"
    root.mkdir()
    (root / "manifest.toml").write_text(
        '[mod]\nid = "M"\nname = "M"\nversion = "1.0.0"\nauthor = "a"\n'
        'description = "d"\ntags = ["t"]\nlicense = "MIT"\n' + body,
        encoding="utf-8")
    errs, _warns = lint.lint_one(root)
    return errs


def _out(capsys) -> str:
    return capsys.readouterr().out


def test_clean_patches_pass(tmp_path, capsys):
    errs = _lint(tmp_path, """
[[patch]]
kind = "stat"
name = "bleed_duration_value"
value = 10

[[patch]]
kind = "stat"
name = "Easy"
min = 5
max = 10

[[patch]]
kind = "texture"
target = "Ui/A.png.Texture.dxt"
donor = "Ui/B.png.Texture.dxt"
""")
    assert errs == 0, _out(capsys)


@pytest.mark.parametrize("body, needle", [
    ('[[patch]]\nkind = "stat"\nname = "Bleed_Duration_Value"\nvaleu = 10\n',
     "unknown key 'valeu' (did you mean 'value'?)"),
    ('[[patch]]\nkind = "stat"\nname = "Bleed_Duraton_Value"\nvalue = 10\n',
     "did you mean 'Bleed_Duration_Value'?"),
    ('[[patch]]\nkind = "stat"\nname = "Easy"\nvalue = 3\n',
     "'Easy' has no 'value' field"),
    ('[[patch]]\nkind = "stat"\nname = "Bleed_Duration_Value"\nvalue = "10"\n',
     "value must be a number"),
    ('[[patch]]\nkind = "texture"\ntarget = "Ui/Nope.png.Texture.dxt"\n'
     'donor = "Ui/B.png.Texture.dxt"\n', "target is not a shipped asset"),
    ('[[patch]]\nkind = "text"\nkey = "x"\n', "unknown patch kind 'text'"),
    ('[[patch]]\nkind = "ot"\nselector = "x"\nfield = "y"\n', "missing 'value'"),
    ('[[content]]\nkind = "boss"\nid = "b"\nbase = "X"\nbecomez = "Y"\n',
     "unknown key 'becomez' (did you mean 'becomes'?)"),
    ('[[content]]\nkind = "widget"\nid = "w"\n', "unknown content kind 'widget'"),
    ('[[content]]\nkind = "talent"\nhero = "Juliet"\n', "needs both 'kind' and 'id'"),
])
def test_mistakes_are_errors(tmp_path, capsys, body, needle):
    errs = _lint(tmp_path, body)
    out = _out(capsys)
    assert errs >= 1, out
    assert needle in out, out


def test_unknown_mod_key_only_warns(tmp_path, capsys):
    root = tmp_path / "M"
    root.mkdir()
    (root / "manifest.toml").write_text(
        '[mod]\nid = "M"\nname = "M"\nversion = "1.0.0"\nauthor = "a"\n'
        'description = "d"\ntags = ["t"]\nlicense = "MIT"\nlicence = "MIT"\n',
        encoding="utf-8")
    errs, warns = lint.lint_one(root)
    out = _out(capsys)
    assert errs == 0 and warns >= 1, out
    assert "unknown key 'licence' (did you mean 'license'?)" in out
