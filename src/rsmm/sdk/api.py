"""SDK API stability contract.

Plugins and mods can pin against `rsmm.sdk.api.v1` so a SDK bump that
breaks them is detected at load time, not at first crash.

Bump `API_VERSION` (semver) on any breaking change to the public surface.
Non-breaking additions = minor bump. Anything else = major bump.
"""

from __future__ import annotations

import functools
import re

from rsmm.manifest_graph import _parse_version, _version_ok

API_VERSION: str = "1.0.0"

_REGISTRY: dict[str, callable] = {}


def sdk_export(name: str | None = None):
    """Mark a function as part of the public SDK surface.

    `rsmm sdk-doctor --list-api` enumerates these; the auto-doc pass
    consumes them to generate `docs/api/`.
    """

    def deco(fn):
        key = name or fn.__name__
        if key in _REGISTRY and _REGISTRY[key] is not fn:
            raise RuntimeError(f"sdk_export: duplicate name {key!r}")
        _REGISTRY[key] = fn

        @functools.wraps(fn)
        def wrap(*a, **kw):
            return fn(*a, **kw)

        wrap.__sdk_export__ = key
        return wrap

    return deco


def registry() -> dict[str, callable]:
    """Read-only snapshot of the public surface (for doc gen / sdk-doctor)."""
    return dict(_REGISTRY)


# Re-exported so callers that historically reached for `rsmm.sdk.api._parse_v`
# keep working. New code should import directly from `rsmm.manifest_graph`.
_parse_v = _parse_version

_TOKEN = re.compile(r"\s*(>=|<=|==|!=|>|<|=)?\s*([\d.]+)\s*")


def satisfies(have_version: str, spec: str) -> bool:
    """`satisfies("1.2.3", ">=1.0,<2") == True`. Comma-separated AND."""
    if not spec:
        return True
    have = _parse_version(have_version)
    for clause in spec.split(","):
        m = _TOKEN.fullmatch(clause)
        if not m:
            raise ValueError(f"bad version clause: {clause!r}")
        op = m.group(1) or ">="
        if not _version_ok(have, op, _parse_version(m.group(2))):
            return False
    return True


def require_api(spec: str) -> None:
    """Raise if the current SDK API doesn't satisfy `spec`. Called by plugins."""
    if not satisfies(API_VERSION, spec):
        raise RuntimeError(
            f"SDK API {API_VERSION} does not satisfy {spec!r}; "
            f"upgrade RSMM or relax the plugin's constraint."
        )
