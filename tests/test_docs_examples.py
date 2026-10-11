"""Every complete Python SDK example in the docs must run.

The guides are the first code most authors copy, and nothing used to execute
them: on 2026-09-23 the modding guide's main example called `m.ot`, which the
`sdk.Mod` facade did not forward (AttributeError), and another cloned
`base="Marsh_Ghoul"`, an enemy that does not exist. Both read as working code.

A block is an example when it opens a `with sdk.Mod(...)` — fragments that
continue an earlier block (`m.tag(...)` on its own) cannot run alone and are
not collected. Each example is executed against a throwaway mods dir.

Examples that build real content need the vanilla corpus. On CI there is none,
so a "base not found" there is skipped — but only when nothing is readable;
with a game install or the mirror present, the same error fails the test,
because then the example really does name something the game does not ship.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from rsmm.engine import corpus
from rsmm.sdk.content import SchemaNotMined

_DOCS = Path(__file__).resolve().parents[1] / "apps" / "docs" / "src" / "content" / "docs"
_BLOCK = re.compile(r"```python\n(.*?)```", re.S)


def _examples() -> list[tuple[str, str]]:
    out = []
    for md in sorted(_DOCS.rglob("*.md*")):
        for n, m in enumerate(_BLOCK.finditer(md.read_text(encoding="utf-8")), 1):
            code = m.group(1)
            if re.search(r"^\s*with\s+sdk\.Mod\(", code, re.M):
                out.append((f"{md.relative_to(_DOCS)}#{n}", code))
    return out


_EXAMPLES = _examples()


def test_examples_are_found():
    """Guard the collector itself: a regex that matches nothing passes every
    parametrized case vacuously."""
    assert len(_EXAMPLES) >= 4


@pytest.mark.parametrize("where, code", _EXAMPLES, ids=[w for w, _ in _EXAMPLES])
def test_docs_example_runs(where, code, tmp_path, monkeypatch):
    monkeypatch.setattr("rsmm.sdk.builder.MODS_DIR", tmp_path / "mods")
    monkeypatch.chdir(tmp_path)
    from rsmm import sdk

    try:
        exec(compile(code, where, "exec"), {"sdk": sdk, "__name__": "__docs__"})
    except SchemaNotMined as e:
        if corpus.source() == "none":
            pytest.skip(f"needs the vanilla corpus (no game install on this machine): {e}")
        raise
