"""The generic `item-grid` config field: a mod declares sections, filters, a
number and a theme in its own schema; the SDK validates the declaration and the
stored value, and never knows what the grid is for."""

from __future__ import annotations

import tomllib

import pytest

from rsmm.sdk.config import ConfigError, ConfigSchema, ConfigStore
from rsmm.sdk.config_choices import _clean

_SCHEMA = """
[fields.loadout]
type = "item-grid"
label = "Loadout"
source = "item-catalog"
title = "Pick your kit"
number = { attr = "cost", label = "Cost", min = 0, max = 10, editable = "canEdit" }

[[fields.loadout.sections]]
id = "left"
label = "Left hand"
group = "Hands"
accepts = { kind = "weapon" }
count = { label = "Carried", min = 1, max = 3, default = 2 }

[[fields.loadout.sections]]
id = "right"
empty = "Bare-handed"

[fields.loadout.theme]
panel = "Ui/SandMan/UI_SandManBg.png"
header = { texture = "Ui/SandMan/UI_SandMan_categoriesBG.png", ink = "dark" }
"""


def _schema(text: str = _SCHEMA) -> ConfigSchema:
    return ConfigSchema.from_dict(tomllib.loads(text))


def test_declaration_round_trips_to_the_client_shape():
    grid = _schema().fields["loadout"].as_dict()["grid"]
    assert [s["id"] for s in grid["sections"]] == ["left", "right"]
    assert grid["sections"][0]["count"] == {"label": "Carried", "min": 1, "max": 3, "default": 2}
    assert grid["sections"][1]["label"] == "right"      # label defaults to the id
    assert grid["sections"][1]["empty"] == "Bare-handed"
    assert grid["number"]["editable"] == "canEdit"
    # The client learns which slots are themed; the paths stay CLI-side.
    assert grid["themeSlots"] == ["header", "panel"]
    assert grid["themeInk"] == {"header": "dark", "panel": "light"}
    assert grid["layout"] == "stack"
    assert "Ui/" not in str(grid)


@pytest.mark.parametrize("edit, match", [
    (lambda s: s.replace('source = "item-catalog"\n', ""), "needs source"),
    (lambda s: s.replace('ink = "dark"', 'ink = "purple"'), "light or dark"),
    (lambda s: s.replace('title = "Pick your kit"', 'layout = "spiral"'), "layout"),
    (lambda s: s.replace('source = "item-catalog"', 'source = "rm -rf"'), "not a known"),
    (lambda s: s.replace('id = "right"', 'id = "left"'), "declared twice"),
    (lambda s: s.replace('id = "right"', 'id = "no spaces"'), "letters, digits"),
    (lambda s: s.replace("default = 2", "default = 9"), "min <= default <= max"),
    (lambda s: s.replace('panel = "Ui/SandMan/UI_SandManBg.png"', 'panel = "../../secrets.png"'),
     "game texture path"),
    (lambda s: s.replace('panel = "Ui/SandMan/UI_SandManBg.png"', 'body = "Ui/X.png"'),
     "unknown slot"),
])
def test_bad_declarations_are_refused(edit, match):
    with pytest.raises(ConfigError, match=match):
        _schema(edit(_SCHEMA))


def test_value_is_validated_against_the_declaration(tmp_path):
    (tmp_path / "config_schema.toml").write_text(_SCHEMA)
    store = ConfigStore(tmp_path)
    store.set("loadout", {"sections": {"left": {"items": ["b", "a", "a"], "count": 3}},
                          "numbers": {"a.b": 4}})
    assert ConfigStore(tmp_path).get("loadout") == {
        "sections": {"left": {"items": ["a", "b"], "count": 3}}, "numbers": {"a.b": 4}}
    for bad in ({"sections": {"middle": {}}},
                {"sections": {"left": {"items": []}}},
                {"sections": {"left": {"count": 4}}},
                {"sections": {"right": {"count": 1}}},      # right declares no count
                {"numbers": {"a": 11}},
                {"other": 1}):
        with pytest.raises(ConfigError):
            store.set("loadout", bad)


def test_option_attrs_are_bounded_scalars():
    opt = _clean({"id": "x", "attrs": {"n": 1, "ok": True, "tags": ["a"], "nested": {"no": 1},
                                       "mixed": [1, "a"]}})
    assert opt is not None
    assert opt["attrs"] == {"n": 1, "ok": True, "tags": ["a"]}
