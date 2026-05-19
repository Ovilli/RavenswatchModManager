"""Auto-generate docs/api/ from `@sdk_export` registrations.

Walks `rsmm.sdk.api.registry()`, pulls each function's signature +
docstring, and emits one Markdown file per submodule. Run via
`rsmm docs-gen`.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
from pathlib import Path

from .api import registry


def _import_sdk_modules() -> None:
    """Side-effect import every `rsmm.sdk.*` so decorators fire."""
    import rsmm.sdk as pkg
    for _, name, _ in pkgutil.walk_packages(pkg.__path__, prefix="rsmm.sdk."):
        try:
            importlib.import_module(name)
        except Exception:
            pass


def generate(out_dir: Path) -> list[Path]:
    """Write one `<module>.md` per SDK submodule. Returns paths written."""
    _import_sdk_modules()
    out_dir.mkdir(parents=True, exist_ok=True)
    by_module: dict[str, list[tuple[str, callable]]] = {}
    for name, fn in registry().items():
        mod = getattr(fn, "__module__", "rsmm.sdk")
        by_module.setdefault(mod, []).append((name, fn))
    written: list[Path] = []
    for mod_name, items in sorted(by_module.items()):
        slug = mod_name.replace("rsmm.sdk.", "").replace(".", "_") or "root"
        lines = [f"# {mod_name}", ""]
        for name, fn in sorted(items):
            try:
                sig = str(inspect.signature(fn))
            except (TypeError, ValueError):
                sig = "(...)"
            doc = inspect.getdoc(fn) or "(undocumented)"
            lines += [f"## `{name}{sig}`", "", doc, ""]
        p = out_dir / f"{slug}.md"
        p.write_text("\n".join(lines), encoding="utf-8")
        written.append(p)
    index = out_dir / "README.md"
    idx_lines = ["# SDK v3 API reference", "",
                 f"API version: see `rsmm.sdk.api.API_VERSION`", "",
                 "## Modules", ""]
    for p in sorted(written):
        idx_lines.append(f"- [{p.stem}]({p.name})")
    index.write_text("\n".join(idx_lines) + "\n", encoding="utf-8")
    written.append(index)
    return written
