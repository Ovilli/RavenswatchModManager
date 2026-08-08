"""Tests for the per-mod config store and the on-disk format the loader's
native R.config bindings (config_get/config_set/config_all in script_lua.cpp)
read back. The bindings themselves are C++, but they parse the exact
``config.toml`` that ``ConfigStore`` writes, so pinning that format here is the
Python-side contract that keeps the two halves in sync.
"""

from __future__ import annotations

import tomllib

import pytest

from rsmm.sdk.config import ConfigError, ConfigSchema, ConfigStore


def _write_schema(mod_dir, body: str) -> None:
    (mod_dir / "config_schema.toml").write_text(body, encoding="utf-8")


def test_schema_coerces_and_range_checks():
    s = ConfigSchema.from_dict({
        "fields": {
            "count": {"type": "int", "default": 3, "min": 0, "max": 10},
            "mode": {"type": "enum", "choices": ["a", "b"], "default": "a"},
        }
    })
    assert s.fields["count"].coerce("5") == 5
    with pytest.raises(ConfigError):
        s.fields["count"].coerce(11)          # over max
    with pytest.raises(ConfigError):
        s.fields["mode"].coerce("z")          # not a choice


def test_store_get_set_persists_config_section(tmp_path):
    _write_schema(tmp_path, """
[fields.seed]
type = "int"
default = 0
[fields.hard]
type = "bool"
default = false
[fields.label]
type = "string"
default = "hi"
""")
    store = ConfigStore(tmp_path)
    assert store.get("seed") == 0
    store.set("seed", 12345)
    store.set("hard", True)
    store.set("label", 'quote"me')

    # Persisted under a [config] table — exactly what load_mod_config parses.
    raw = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert "config" in raw
    assert raw["config"]["seed"] == 12345
    assert raw["config"]["hard"] is True
    assert raw["config"]["label"] == 'quote"me'   # quoting round-trips

    # A fresh store re-reads the same values (loader-visible state).
    assert ConfigStore(tmp_path).get("seed") == 12345


def test_store_rejects_unknown_key(tmp_path):
    _write_schema(tmp_path, '[fields.seed]\ntype = "int"\ndefault = 0\n')
    store = ConfigStore(tmp_path)
    with pytest.raises(ConfigError):
        store.set("nope", 1)


def test_store_drops_unknown_keys_from_old_configtoml(tmp_path):
    # A config.toml from an older schema version must not break load.
    _write_schema(tmp_path, '[fields.seed]\ntype = "int"\ndefault = 0\n')
    (tmp_path / "config.toml").write_text(
        '[config]\nseed = 7\nremoved_field = 99\n', encoding="utf-8")
    store = ConfigStore(tmp_path)
    assert store.get("seed") == 7
    assert store.get("removed_field") is None


def test_toml_repr_matches_loader_primitive_types(tmp_path):
    # bool/int/float/string are the only types the loader's config_set accepts;
    # verify our emitter produces each in a form tomllib (and toml++) parse.
    _write_schema(tmp_path, """
[fields.b]
type = "bool"
[fields.i]
type = "int"
[fields.f]
type = "float"
[fields.s]
type = "string"
""")
    store = ConfigStore(tmp_path)
    store.replace({"b": True, "i": -4, "f": 1.5, "s": "x"})
    parsed = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))["config"]
    assert parsed == {"b": True, "i": -4, "f": 1.5, "s": "x"}


def test_control_characters_survive_the_toml_round_trip(tmp_path):
    """Regression: `_toml_repr` escaped only `\\` and `"`.

    TOML basic strings forbid raw control characters, so a value containing a
    newline — which the desktop config editor accepts — wrote a config.toml
    that parsed nowhere. The mod's config was then permanently unreadable:
    every later `reload()` raised, and the only repair was deleting the file
    by hand.
    """
    _write_schema(tmp_path, '[fields.note]\ntype = "string"\ndefault = "hi"\n')
    store = ConfigStore(tmp_path)
    payload = 'line1\nline2\r\ttab "quoted" back\\slash \x01 \x7f'
    store.replace({"note": payload})

    text = (tmp_path / "config.toml").read_text(encoding="utf-8")
    assert tomllib.loads(text)["config"]["note"] == payload   # parses at all
    store.reload()
    assert store.get("note") == payload                        # and survives


def test_non_bare_field_name_is_quoted_not_dotted(tmp_path):
    """A field named `a.b` must stay one key, not become a nested table.

    Emitted raw, `a.b = "x"` is a TOML *dotted* key: it round-trips back as
    `{"a": {"b": "x"}}`, so the field reads as permanently missing.
    """
    _write_schema(tmp_path, '[fields."a.b"]\ntype = "string"\ndefault = "x"\n')
    store = ConfigStore(tmp_path)
    store.replace({"a.b": "dotted"})

    raw = tomllib.loads((tmp_path / "config.toml").read_text(encoding="utf-8"))
    assert raw["config"] == {"a.b": "dotted"}
    store.reload()
    assert store.get("a.b") == "dotted"


def test_persist_leaves_no_temp_file(tmp_path):
    """Writes go through safeio, so nothing is left beside config.toml."""
    _write_schema(tmp_path, '[fields.n]\ntype = "int"\ndefault = 1\n')
    ConfigStore(tmp_path).replace({"n": 2})
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "config.toml", "config_schema.toml",
    ]
