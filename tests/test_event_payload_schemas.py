"""Guard the mined gameplay-event payload schemas and the header generated
from them.

The decode itself only runs inside the game, so what CI can hold onto is the
pipeline: the schemas in data/symbols.json must stay well-formed, must keep
the layouts we confirmed by hand, and the generated C++ table must agree with
them (sorted, complete, correctly typed) — the binary search in the loader is
wrong the moment the table is not ordered by vftable RVA.
"""

from __future__ import annotations

import re

from rsmm.engine.paths import REPO_ROOT
from rsmm.engine.symbols import load_symbol_map

GEN = REPO_ROOT / "src" / "loader" / "src" / "event_fields.gen.h"

# Offsets established by hand in docs/_re/kinds/events-bus.md, long before the
# miner existed. If a re-mine stops reproducing these, the miner regressed.
CONFIRMED = {
    "oCGameNamedEventNetworkDamage": {"0x40": ("f32", "value"),
                                      "0x48": ("u64", "source_id")},
    "NamedEventGiveMagicalObject": {"0x50": ("u64", "mo_guid_lo"),
                                    "0x58": ("u64", "mo_guid_hi")},
}

VALID_TYPES = {"u8", "u16", "u32", "u64", "f32", "f64"}
HEADER_END = 0x38


def _schemas():
    return {c["class"]: c for c in load_symbol_map().event_payload_schemas}


def test_schemas_are_well_formed():
    schemas = _schemas()
    assert schemas, "no event payload schemas in data/symbols.json"
    for cls, entry in schemas.items():
        assert entry["fields"], f"{cls} has an empty field list"
        assert entry["vftable_rvas"], f"{cls} has no vftable"
        seen = set()
        for f in entry["fields"]:
            off = int(f["off"], 16)
            # Anything below the header is the event's own vftable/name/id,
            # never payload — a schema reaching in there means the miner
            # mis-anchored the object.
            assert off >= HEADER_END, f"{cls} field {f['name']} inside the header"
            assert off < 0x400, f"{cls} field {f['name']} implausibly far out"
            assert f["type"] in VALID_TYPES, f"{cls}.{f['name']} bad type {f['type']}"
            assert f["off"] not in seen, f"{cls} has duplicate offset {f['off']}"
            seen.add(f["off"])


def test_hand_confirmed_layouts_survive():
    schemas = _schemas()
    for cls, fields in CONFIRMED.items():
        assert cls in schemas, f"{cls} missing from the mined schemas"
        got = {f["off"]: (f["type"], f["name"]) for f in schemas[cls]["fields"]}
        for off, expect in fields.items():
            assert got.get(off) == expect, (
                f"{cls} @{off}: expected {expect}, got {got.get(off)}"
            )


def test_generated_header_matches_the_schemas():
    text = GEN.read_text()
    schemas = _schemas()
    for cls in schemas:
        assert f'"{cls}"' in text, f"{cls} absent from {GEN.name}"
    # Every field name must reach the header, since that is the JSON key mods
    # read off the payload.
    for cls, entry in schemas.items():
        for f in entry["fields"]:
            assert f'"{f["name"]}"' in text, f"{cls}.{f['name']} absent from the header"


def test_generated_table_is_sorted_for_binary_search():
    text = GEN.read_text()
    rows = re.findall(r"\{ (0x[0-9a-f]+)u, \"", text)
    assert rows, "no schema rows found in the generated header"
    rvas = [int(r, 16) for r in rows]
    assert rvas == sorted(rvas), "kEventSchemas must be sorted by vftable RVA"
    assert len(set(rvas)) == len(rvas), "duplicate vftable RVA in kEventSchemas"


def test_no_base_class_schemas():
    """The base classes are header-only by construction.

    Their vftable is stored by every derived constructor, so a naive union of
    the writes attributes all the subclasses' fields to the base — which would
    make the loader decode nonsense for every plain event. The miner drops
    them by construction-site count; this pins that.
    """
    schemas = _schemas()
    for base in ("oCGameNamedEvent", "oCGameNamedEventNetwork"):
        assert base not in schemas, f"{base} must not carry a payload schema"
