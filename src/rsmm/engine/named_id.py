"""The engine's 32-bit NAME ids: how a string becomes the u32 cooked data stores.

``id = NamedEvent_Id_FromCrc(0, crc32(name))`` — the standard reflected CRC-32
of the name, then a second CRC-32 over the 8 bytes of ``(namespace, crc)``
interleaved byte-wise ``[ns0, c0, ns1, c1, ns2, c2, ns3, c3]`` (see
``data/symbols.json``: ``NamedEvent_Id_FromCrc``, ``Id_HashString``).

The same scheme names named events (``"GAIN_REROLL"``) and INGREDIENTS: an
ingredient definition stores this id of its name, and every component that
gains or delivers an ingredient (``oCDtEntityCpntIngredientGainSettings``,
``oCDtEntityCpntDeliveryPointSettings``) stores the id, never a path. Verified
2026-11-15 against every shipped ingredient: Straw 0xe9f9a52e, Stone
0x51f94a7c, Wood 0x48b35820, Key 0xc4cb986e, Bean 0xf0d7307d.
"""

from __future__ import annotations

import struct
import zlib


def from_crc(namespace: int, crc: int) -> int:
    """``NamedEvent_Id_FromCrc(namespace, crc)``."""
    a, b = struct.pack("<I", namespace & 0xFFFFFFFF), struct.pack("<I", crc & 0xFFFFFFFF)
    return zlib.crc32(bytes(x for pair in zip(a, b, strict=True) for x in pair)) & 0xFFFFFFFF


def of(name: str) -> int:
    """The id the engine interns ``name`` as (``Id_HashString``)."""
    return from_crc(0, zlib.crc32(name.encode("utf-8")))


def to_bytes(name: str) -> bytes:
    """The id as it sits in cooked data (little-endian u32)."""
    return struct.pack("<I", of(name))
