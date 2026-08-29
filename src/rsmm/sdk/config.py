"""Per-mod config: schema validation + persisted store.

Schema:
    {fields.<key>.{type, default, min, max, label, choices, enum, source}}

Types: bool, int, float, string, enum, multiselect.

A `multiselect` field holds a LIST of ids. Its options are either spelled out
in `choices`, or fetched from an allowlisted provider named by `source` — see
`rsmm.sdk.config_choices`. A provider supplies a label, a group and an icon per
option, which is what lets the client draw a searchable grid of game art
instead of a wall of internal ids.

Storage:
    mods/<id>/config.toml  — user-edited values
    mods/<id>/config_schema.toml  — schema (authored by modder)
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rsmm.engine.safeio import atomic_write_text

from .api import sdk_export

_TYPES = {"bool", "int", "float", "string", "enum", "multiselect"}

#: The escapes TOML defines a short form for. Every other control character
#: goes out as `\uXXXX` — see `ConfigStore._toml_repr`.
_TOML_ESCAPES = {
    "\\": "\\\\",
    '"': '\\"',
    "\b": "\\b",
    "\t": "\\t",
    "\n": "\\n",
    "\f": "\\f",
    "\r": "\\r",
}


class ConfigError(ValueError):
    pass


def _check_source(name: str, raw: Any) -> str | None:
    """Validate a `multiselect` field's option provider against the allowlist."""
    if raw is None:
        return None
    from .config_choices import PROVIDERS
    src = str(raw)
    if src not in PROVIDERS:
        raise ConfigError(
            f"{name}: source {src!r} is not a known option provider "
            f"(one of {', '.join(sorted(PROVIDERS))})"
        )
    return src


@dataclass
class Field:
    name: str
    type: str
    default: Any = None
    min: float | int | None = None
    max: float | int | None = None
    choices: list[str] = field(default_factory=list)
    label: str = ""
    #: Allowlisted option provider for a `multiselect`. A NAME, never a path or
    #: a command: the desktop webview can spawn the CLI, so anything a mod
    #: could inject here would run on the player's machine.
    source: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "default": self.default,
            "min": self.min,
            "max": self.max,
            "choices": list(self.choices),
            "label": self.label,
            "source": self.source,
        }

    def coerce(self, value: Any) -> Any:
        if self.type == "bool":
            if isinstance(value, bool):
                return value
            if isinstance(value, str):
                return value.lower() in ("1", "true", "yes", "on")
            return bool(value)
        if self.type == "int":
            v = int(value)
            self._range_check(v)
            return v
        if self.type == "float":
            v = float(value)
            self._range_check(v)
            return v
        if self.type == "string":
            return str(value)
        if self.type == "enum":
            v = str(value)
            if self.choices and v not in self.choices:
                raise ConfigError(
                    f"{self.name}: {v!r} not in {self.choices}"
                )
            return v
        if self.type == "multiselect":
            if isinstance(value, str):
                value = [value]
            if not isinstance(value, (list, tuple)):
                raise ConfigError(f"{self.name}: expected a list of ids")
            out = sorted({str(x) for x in value if str(x).strip()})
            # A `source` field's valid set lives in the game install and can be
            # absent (no install yet, a game update). Rejecting an unknown id
            # here would DELETE the player's selection the first time the CLI
            # ran somewhere the catalog could not be read, so membership is
            # only enforced for a statically declared `choices` list.
            if self.choices and self.source is None:
                bad = [v for v in out if v not in self.choices]
                if bad:
                    raise ConfigError(f"{self.name}: {bad} not in {self.choices}")
            return out
        raise ConfigError(f"{self.name}: unknown type {self.type!r}")

    def _range_check(self, v: float | int) -> None:
        if self.min is not None and v < self.min:
            raise ConfigError(f"{self.name}: {v} < min {self.min}")
        if self.max is not None and v > self.max:
            raise ConfigError(f"{self.name}: {v} > max {self.max}")


@dataclass
class ConfigSchema:
    fields: dict[str, Field] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict) -> ConfigSchema:
        s = cls()
        for name, body in (raw.get("fields") or {}).items():
            t = body.get("type")
            if t not in _TYPES:
                raise ConfigError(f"{name}: type must be one of {sorted(_TYPES)}")
            s.fields[name] = Field(
                name=name,
                type=t,
                default=body.get("default"),
                min=body.get("min"),
                max=body.get("max"),
                choices=list(body.get("choices", []) or []),
                label=str(body.get("label", name)),
                source=_check_source(name, body.get("source")),
            )
            # Validate the default eagerly so a broken schema fails at build.
            if s.fields[name].default is not None:
                s.fields[name].coerce(s.fields[name].default)
        return s

    @classmethod
    def load(cls, path: Path) -> ConfigSchema:
        if not path.exists():
            return cls()
        return cls.from_dict(tomllib.loads(path.read_text(encoding="utf-8")))

    def defaults(self) -> dict[str, Any]:
        return {n: f.default for n, f in self.fields.items() if f.default is not None}

    def validate(self, values: dict[str, Any]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for k, v in values.items():
            if k not in self.fields:
                # Unknown keys are silently dropped, not rejected. This lets
                # a schema add/remove fields without invalidating an old
                # config.toml from a previous version.
                continue
            out[k] = self.fields[k].coerce(v)
        return out


class ConfigStore:
    """Persisted, schema-validated config for one mod."""

    def __init__(self, mod_dir: Path):
        self.mod_dir = mod_dir
        self.schema_path = mod_dir / "config_schema.toml"
        self.values_path = mod_dir / "config.toml"
        self.schema = ConfigSchema.load(self.schema_path)
        self._values: dict[str, Any] = {}
        self.reload()

    def reload(self) -> None:
        merged = dict(self.schema.defaults())
        if self.values_path.exists():
            try:
                raw = tomllib.loads(self.values_path.read_text(encoding="utf-8"))
                user = raw.get("config") or raw
                merged.update(self.schema.validate(user))
            except Exception as e:
                raise ConfigError(f"{self.values_path}: {e}") from e
        self._values = merged

    def as_dict(self) -> dict[str, Any]:
        return dict(self._values)

    def schema_as_dict(self) -> dict[str, Any]:
        return {
            "fields": {name: field.as_dict() for name, field in self.schema.fields.items()}
        }

    @sdk_export("ConfigStore.get")
    def get(self, key: str, fallback: Any = None) -> Any:
        """Read a config value by key, returning ``fallback`` if unset."""
        return self._values.get(key, fallback)

    @sdk_export("ConfigStore.set")
    def set(self, key: str, value: Any) -> None:
        """Set a config value, coercing to the schema field's type and persisting.

        Raises ``ConfigError`` if ``key`` is not declared in the schema.
        """
        if key not in self.schema.fields:
            raise ConfigError(f"unknown config key {key!r}")
        self._values[key] = self.schema.fields[key].coerce(value)
        self._persist()

    def replace(self, values: dict[str, Any]) -> None:
        unknown = [key for key in values if key not in self.schema.fields]
        if unknown:
            raise ConfigError(f"unknown config key {unknown[0]!r}")
        merged = dict(self.schema.defaults())
        for key, value in values.items():
            merged[key] = self.schema.fields[key].coerce(value)
        self._values = merged
        self._persist()

    def _persist(self) -> None:
        # Hand-emit TOML to avoid a hard dep. We only emit primitive types
        # the schema permits, so this is straightforward.
        lines = ["[config]"]
        for k in sorted(self._values):
            v = self._values[k]
            lines.append(f"{self._toml_key(k)} = {self._toml_repr(v)}")
        # Durable + atomic: a torn config.toml is as unrecoverable for the mod
        # as a torn asset is for the install, and `tmp.write_text` alone can
        # leave an empty file behind a completed rename after a crash.
        atomic_write_text(self.values_path, "\n".join(lines) + "\n")

    @staticmethod
    def _toml_key(k: str) -> str:
        """Emit `k` as a TOML key, quoting it when it is not a bare key.

        Field names come from the modder's `config_schema.toml`, so they are
        not guaranteed bare. Emitting one raw is not merely ugly: `a.b = 1` is
        a *dotted* key, so a field literally named `a.b` would round-trip back
        as a nested table and read as a missing key forever.
        """
        if k and all(c.isalnum() or c in "-_" for c in k) and k.isascii():
            return k
        return ConfigStore._toml_repr(k)

    @staticmethod
    def _toml_repr(v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        if isinstance(v, (list, tuple)):
            return "[" + ", ".join(ConfigStore._toml_repr(x) for x in v) + "]"
        # String. Escaping only `\` and `"` was not enough: TOML basic strings
        # forbid raw control characters, so a value containing a newline — which
        # the desktop config editor happily accepts — produced a config.toml
        # that wrote fine and then failed to parse on every subsequent load,
        # permanently bricking that mod's config. The loader reads the same
        # file through toml++ and rejected it just as hard, logging
        # `[config] parse fail` and running the mod with no config at all.
        # (The native writer, `config_write_file` in script_lua.cpp, serialises
        # through toml++ and was always correct — only this side was not.)
        out = []
        for ch in str(v):
            esc = _TOML_ESCAPES.get(ch)
            if esc is not None:
                out.append(esc)
            elif ch < "\x20" or ch == "\x7f":
                out.append(f"\\u{ord(ch):04x}")
            else:
                out.append(ch)
        return '"' + "".join(out) + '"'
