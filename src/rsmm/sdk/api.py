"""SDK API stability contract.

Plugins and mods can pin against `rsmm.sdk.api.v1` so a SDK bump that
breaks them is detected at load time, not at first crash.

Bump `API_VERSION` (semver) on any breaking change to the public surface.
Non-breaking additions = minor bump. Anything else = major bump.
"""

from __future__ import annotations

import functools
import operator
import re

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


# --- semver-spec parser (shared by plugins, repo, intermod) ----------------

_OPS = {
    ">=": operator.ge, "<=": operator.le,
    ">":  operator.gt, "<":  operator.lt,
    "==": operator.eq, "=":  operator.eq, "!=": operator.ne,
}
_TOKEN = re.compile(r"\s*(>=|<=|==|!=|>|<|=)?\s*([\d.]+)\s*")


def _parse_v(s: str) -> tuple[int, ...]:
    parts = re.findall(r"\d+", s or "")
    return tuple(int(p) for p in parts) or (0,)


def _pad(a: tuple[int, ...], b: tuple[int, ...]) -> tuple[tuple, tuple]:
    n = max(len(a), len(b))
    return a + (0,) * (n - len(a)), b + (0,) * (n - len(b))


def _match_one(have: tuple[int, ...], op: str, want: tuple[int, ...]) -> bool:
    fn = _OPS.get(op or ">=")
    h, w = _pad(have, want)
    return fn(h, w) if fn else True


def satisfies(have_version: str, spec: str) -> bool:
    """`satisfies("1.2.3", ">=1.0,<2") == True`. Comma-separated AND."""
    if not spec:
        return True
    have = _parse_v(have_version)
    for clause in spec.split(","):
        m = _TOKEN.fullmatch(clause)
        if not m:
            raise ValueError(f"bad version clause: {clause!r}")
        op, ver = m.group(1) or ">=", m.group(2)
        if not _match_one(have, op, _parse_v(ver)):
            return False
    return True


def require_api(spec: str) -> None:
    """Raise if the current SDK API doesn't satisfy `spec`. Called by plugins."""
    if not satisfies(API_VERSION, spec):
        raise RuntimeError(
            f"SDK API {API_VERSION} does not satisfy {spec!r}; "
            f"upgrade RSMM or relax the plugin's constraint."
        )
