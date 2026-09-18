"""Docs must not drift from `KIND_CONFIDENCE`.

The per-kind table is generated (`rsmm docs-gen` → reference/sdk-api/kinds.md,
`--check`ed in CI). What generation cannot reach is prose: a hand-kept table
that pairs a kind with a rating went stale the first time a kind was proven
(modding.md still called `mesh` experimental and claimed only item + talent were
confirmed after `poi` and `mesh` both were). So prose may link, never restate.

The first-mod guide is checked the other way round: it must have a section for
every kind, each with a complete manifest whose `experimental` flag is exactly
what the kind's rating demands — a snippet missing it fails `rsmm lint` on the
reader's first try, and one carrying it needlessly teaches the wrong habit.
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from rsmm.sdk.content import KIND_CONFIDENCE, KINDS

DOCS = Path(__file__).resolve().parent.parent / "apps" / "docs" / "src" / "content" / "docs"
GUIDE = DOCS / "guides" / "first-mod-by-kind.md"

_RATING = re.compile(r"✅|⚠️|❓|\b(confirmed|experimental|guess)\b")
_KIND_REF = re.compile(r'kind\s*=\s*"([a-z_]+)"')


def _prose_pages() -> list[Path]:
    generated = DOCS / "reference" / "sdk-api"
    return [p for p in DOCS.rglob("*.md*") if generated not in p.parents]


def test_prose_tables_do_not_restate_kind_ratings():
    offenders = []
    for page in _prose_pages():
        for n, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            if not line.lstrip().startswith("|"):
                continue
            kinds = [k for k in _KIND_REF.findall(line) if k in KINDS]
            if kinds and _RATING.search(line):
                offenders.append(f"{page.relative_to(DOCS)}:{n} ({', '.join(kinds)})")
    assert not offenders, (
        "a prose table pairs a content kind with a rating — link to "
        "/reference/sdk-api/kinds/ instead (generated from KIND_CONFIDENCE):\n  "
        + "\n  ".join(offenders)
    )


def _guide_sections() -> dict[str, str]:
    text = GUIDE.read_text(encoding="utf-8")
    parts = re.split(r"^## `([a-z_]+)` — .*$", text, flags=re.M)
    # re.split with one group: [preamble, kind, body, kind, body, ...]
    return dict(zip(parts[1::2], parts[2::2], strict=True))


def test_guide_covers_every_kind():
    sections = _guide_sections()
    assert set(sections) == set(KINDS), (
        f"missing: {sorted(set(KINDS) - set(sections))}, "
        f"unknown: {sorted(set(sections) - set(KINDS))}"
    )


def test_guide_manifests_match_kind_confidence():
    for kind, body in _guide_sections().items():
        blocks = re.findall(r"```toml\n(.*?)```", body, flags=re.S)
        assert blocks, f"{kind}: no manifest snippet"
        docs = [tomllib.loads(b) for b in blocks]
        if kind == "poi":
            # A POI is a folder (`pois/<name>/poi.toml`), not a [[content]] block.
            assert any("base" in d and "chapters" in d for d in docs), (
                "poi: no poi.toml snippet with `base` and `chapters`"
            )
            docs = [d for d in docs if "mod" in d]
            if not docs:
                continue
        doc = docs[0]
        contents = doc.get("content") or []
        assert any(c.get("kind") == kind for c in contents), (
            f"{kind}: the section's manifest registers no kind={kind!r} content"
        )
        needs = KIND_CONFIDENCE.get(kind, "guess") != "confirmed"
        has = bool(doc.get("mod", {}).get("experimental"))
        assert has == needs, (
            f"{kind} is {KIND_CONFIDENCE.get(kind)!r} but its snippet "
            f"{'lacks' if needs else 'carries'} `experimental = true`"
        )
