"""SDK builder authors the store-facing metadata fields
(`packages/schemas` modManifestSchema), validated locally before publish.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from rsmm.sdk.builder import ModBuilder

#: Field names modManifestSchema (packages/schemas/src/mod.ts) accepts. The
#: builder must only ever emit a subset of these under [mod].
_SCHEMA_FIELDS = {
    "id", "name", "version", "author", "summary", "description", "license",
    "repo_url", "homepage_url", "tags", "enabled", "dependencies",
    "sdk_version", "game_build", "min_loader",
    # rsmm-local extensions the schema tolerates as extra keys:
    "experimental", "load_order", "priority", "requires", "recommends",
    "suggests", "conflicts", "replaces",
}


def _emit(mb: ModBuilder, tmp_path: Path) -> dict:
    mb._write_manifest(tmp_path)
    return tomllib.loads((tmp_path / "manifest.toml").read_text())["mod"]


def test_metadata_emitted_with_schema_field_names(tmp_path):
    mb = ModBuilder("MetaMod", version="1.2.0", author="me", name="Meta")
    mb.metadata(summary="tagline", description="long", license="MIT",
                repo_url="https://github.com/me/m",
                homepage_url="https://example.com",
                tags=["cosmetic", "ui"], game_build="1.2.3", min_loader=">=0.5")
    mod = _emit(mb, tmp_path)
    assert mod["summary"] == "tagline"
    assert mod["description"] == "long"
    assert mod["license"] == "MIT"
    assert mod["repo_url"].startswith("https://")
    assert mod["tags"] == ["cosmetic", "ui"]
    assert mod["game_build"] == "1.2.3" and mod["min_loader"] == ">=0.5"
    # never emit a key the canonical schema doesn't know.
    assert set(mod) <= _SCHEMA_FIELDS


def test_no_metadata_emits_nothing_extra(tmp_path):
    mb = ModBuilder("Plain", version="1.0.0", author="me", name="Plain")
    mod = _emit(mb, tmp_path)
    for k in ("summary", "description", "license", "tags", "repo_url"):
        assert k not in mod


@pytest.mark.parametrize("kwargs,msg", [
    ({"license": "x" * 65}, "exceeds 64"),
    ({"summary": "x" * 513}, "exceeds 512"),
    ({"description": "x" * 8193}, "exceeds 8192"),
    ({"repo_url": "not-a-url"}, "must be a URL"),
    ({"homepage_url": "ftpsomething"}, "must be a URL"),
    ({"tags": ["x"] * 17}, "at most 16"),
    ({"tags": ["x" * 33]}, "each"),
])
def test_metadata_validation_rejects(kwargs, msg):
    mb = ModBuilder("M", version="1.0.0", author="me", name="M")
    with pytest.raises(ValueError, match=msg):
        mb.metadata(**kwargs)


def test_metadata_roundtrips_through_summary(tmp_path):
    mb = ModBuilder("M", version="1.0.0", author="me", name="M")
    mb.metadata(summary="s", tags=["a"])
    assert mb.summary()["metadata"] == {"summary": "s", "tags": ["a"]}


def test_quotes_escaped_in_metadata(tmp_path):
    mb = ModBuilder("M", version="1.0.0", author="me", name="M")
    mb.metadata(description='he said "hi" \\ ok')
    mod = _emit(mb, tmp_path)  # must still parse as valid TOML
    assert mod["description"] == 'he said "hi" \\ ok'
