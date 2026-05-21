"""Per-mod config: schema validation + persisted store.

Schema:
    {fields.<key>.{type, default, min, max, label, choices, enum}}

Types: bool, int, float, string, enum.

Storage:
    mods/<id>/config.toml  — user-edited values
    mods/<id>/config_schema.toml  — schema (authored by modder)
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .api import sdk_export

_TYPES = {"bool", "int", "float", "string", "enum"}


class ConfigError(ValueError):
    pass


@dataclass
class Field:
    name: str
    type: str
    default: Any = None
    min: float | int | None = None
    max: float | int | None = None
    choices: list[str] = field(default_factory=list)
    label: str = ""

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

    @sdk_export("ConfigStore.get")
    def get(self, key: str, fallback: Any = None) -> Any:
        return self._values.get(key, fallback)

    @sdk_export("ConfigStore.set")
    def set(self, key: str, value: Any) -> None:
        if key not in self.schema.fields:
            raise ConfigError(f"unknown config key {key!r}")
        self._values[key] = self.schema.fields[key].coerce(value)
        self._persist()

    def update(self, values: dict[str, Any]) -> None:
        self._values.update(self.schema.validate(values))
        self._persist()

    def all(self) -> dict[str, Any]:
        return dict(self._values)

    def _persist(self) -> None:
        # Hand-emit TOML to avoid a hard dep. We only emit primitive types
        # the schema permits, so this is straightforward.
        lines = ["[config]"]
        for k in sorted(self._values):
            v = self._values[k]
            lines.append(f"{k} = {self._toml_repr(v)}")
        tmp = self.values_path.with_suffix(self.values_path.suffix + ".tmp")
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        tmp.replace(self.values_path)

    @staticmethod
    def _toml_repr(v: Any) -> str:
        if isinstance(v, bool):
            return "true" if v else "false"
        if isinstance(v, (int, float)):
            return str(v)
        # string
        s = str(v).replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'
