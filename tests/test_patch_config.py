"""`[[patch]]` fields may read the mod's config: { config = "<field>", times = n }."""

import pytest

from rsmm.cli.merge import _resolve_config
from rsmm.sdk.config import ConfigError


def _mod(tmp_path, saved=""):
    (tmp_path / "config_schema.toml").write_text(
        '[fields.pack]\ntype = "float"\ndefault = 1.5\n', encoding="utf-8")
    if saved:
        (tmp_path / "config.toml").write_text(saved, encoding="utf-8")
    return tmp_path


def test_config_refs_resolve_and_literals_pass_through(tmp_path):
    data = {"name": "Easy", "min": {"config": "pack", "times": 10}, "max": 20}
    assert _resolve_config(_mod(tmp_path), data) == {"name": "Easy", "min": 15.0, "max": 20}


def test_the_players_saved_value_wins_over_the_default(tmp_path):
    out = _resolve_config(_mod(tmp_path, "pack = 2.0\n"), {"min": {"config": "pack", "times": 10}})
    assert out["min"] == 20.0


def test_an_unknown_field_is_an_error(tmp_path):
    with pytest.raises(ConfigError, match="not a field"):
        _resolve_config(_mod(tmp_path), {"min": {"config": "nope"}})
