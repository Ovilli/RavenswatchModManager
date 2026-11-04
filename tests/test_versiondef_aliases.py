"""A custom hero's Update 6 layer: an AliasOverride {its alias -> its
`_Update6` entity} appended to LiveOps6.versiondef, as each shipped hero has."""

from __future__ import annotations

import re

import pytest

from rsmm.engine import cooked, corpus
from rsmm.engine import versiondef as VD

_GEN = "Definitions/Versions/LiveOps6.versiondef.ot.rsionDefinition.gen"
_ENTRY = re.compile(rb"\x11\x11\xbb\xaa\x05\x00\x00\x00(.{16})\x22\x22\xbb\xaa"
                    rb"\x0e\x00\x00\x00EntitySettings(....)", re.S)


def _pristine() -> bytes:
    raw = corpus.read(_GEN)
    if raw is None:
        pytest.skip("LiveOps6 versiondef not available (no mirror, no install)")
    return raw


def _entries(raw: bytes) -> list[tuple[bytes, str]]:
    return [(m[1], raw[m.end():m.end() + int.from_bytes(m[2], "little")].decode("latin1"))
            for m in _ENTRY.finditer(raw)]


def test_scarlets_alias_is_redirected_to_her_update6_entity():
    got = dict(_entries(_pristine()))
    assert bytes.fromhex("ff09241964c1264891fab0f8b1313e18") in got
    assert got[bytes.fromhex("ff09241964c1264891fab0f8b1313e18")].endswith(
        "Hero_Red_Update6.entity.ot")


def test_an_entry_is_appended_as_a_listed_object_and_only_once():
    raw = _pristine()
    guid = bytes(range(16))
    stream = "Heroes\\Hero_Red\\Hero_BloodWolf_Update6.entity.ot"
    out = VD._patch_versiondef_aliases(raw, [(guid, stream)])
    before, after = _entries(raw), _entries(out)
    assert after == [*before, (guid, stream)]
    cf = cooked.parse(out)
    n = len(after)
    # The header and the root both list it: an object neither vector names is
    # an orphan the engine never builds.
    assert int.from_bytes(cf.sections[0].payload[:4], "little") == n
    assert len(cf.sections) == n + 2
    ids = b"".join(i.to_bytes(4, "little") for i in range(n))
    assert n.to_bytes(4, "little") + ids in cf.sections[-1].payload
    assert VD._patch_versiondef_aliases(out, [(guid, stream)]) == out
    assert VD._patch_versiondef_aliases(raw, []) == raw
