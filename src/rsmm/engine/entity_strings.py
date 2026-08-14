"""Length-prefixed string surgery inside cooked entity-settings payloads.

Cooked entity files (``*.entity.ot`` / ``*.EntitySettingsResource.gen``) embed
every cross-entity reference, label key, texture path and event name as an
engine lstr — ``u32 length + utf-8 bytes`` — inside section payloads (see the
``Main_Book_Menu`` recon in docs/_re/kinds/ui-menus.md: page wiring is path
STRINGS like ``GameUis\\All_Book_Pages\\Play_Book_Page.entity.ot``, not GUIDs).

Deserializers consume payloads strictly sequentially (no absolute offsets into
a payload — verified across the rewarddef/entity grammar work), so replacing an
lstr in place — including with a different length, as long as the u32 prefix is
rewritten — keeps the stream well-formed. That makes "clone an entity and
retarget its references / relabel its text keys" a byte-safe operation without
a full per-class codec.

Scan heuristic: a candidate lstr is a u32 ``n`` (1..``_MAX_LEN``) followed by
``n`` printable-ASCII bytes. Replacement only fires on an exact whole-string
match, so a false-positive site can only be rewritten if it byte-for-byte spells
the requested source string — acceptable for the path-like strings this exists
for. Callers pass full strings (not substrings) for the same reason.
"""

from __future__ import annotations

import struct

from . import cooked

_MAX_LEN = 4096
# Printable ASCII; engine identifiers/paths/keys never carry control bytes.
_PRINTABLE = frozenset(range(0x20, 0x7F))
# Same set as bytes, for the C-speed `translate` test in _scan_payload.
_PRINTABLE_BYTES = bytes(range(0x20, 0x7F))


class EntityStringError(ValueError):
    pass


def _scan_payload(payload: bytes) -> list[tuple[int, str]]:
    """Return [(offset_of_length_prefix, string)] for every candidate lstr.

    This is the hottest function in `apply`: it runs at every byte offset of
    every section of every cooked file the corpus sweeps touch, which on a real
    install was ~114k calls and 251 MILLION `struct.unpack_from` calls — 75% of
    total runtime. Two changes remove nearly all of that without altering what
    counts as a candidate:

    * A length prefix must satisfy ``1 <= n <= 4096``, so its top byte is
      always zero and its second-from-top is at most 0x10. Two array indexes
      reject ~99.6% of offsets before any `struct` call is made.
    * `all(b in _PRINTABLE for b in chunk)` built a generator and a set lookup
      per byte. `bytes.translate` deletes every printable byte in C and leaves
      an empty result exactly when the chunk was all-printable.

    The accepted set is unchanged, and `tests/test_entity_strings.py` compares
    this against the straightforward implementation over the shipped corpus.
    """
    out: list[tuple[int, str]] = []
    i, end = 0, len(payload) - 4
    while i <= end:
        # Cheap rejection first — see docstring. `_MAX_LEN` is 4096, so a valid
        # prefix looks like 00 00 <=10 xx in little-endian byte order.
        if payload[i + 3] or payload[i + 2] > (_MAX_LEN >> 8):
            i += 1
            continue
        n = payload[i] | (payload[i + 1] << 8) | (payload[i + 2] << 16)
        if 1 <= n <= _MAX_LEN and i + 4 + n <= len(payload):
            chunk = payload[i + 4:i + 4 + n]
            if not chunk.translate(None, _PRINTABLE_BYTES):
                out.append((i, chunk.decode("ascii")))
                i += 4 + n
                continue
        i += 1
    return out


def list_strings(cooked_bytes: bytes) -> list[tuple[int, int, str]]:
    """All candidate lstrs in a cooked container: [(section, offset, string)]."""
    cf = cooked.parse(cooked_bytes)
    out: list[tuple[int, int, str]] = []
    for si, sec in enumerate(cf.sections):
        out.extend((si, off, s) for off, s in _scan_payload(sec.payload))
    return out


def replace_strings(cooked_bytes: bytes, mapping: dict[str, str],
                    *, require_all: bool = True) -> bytes:
    """Replace whole lstrs per ``mapping`` (exact match) and re-emit.

    Every occurrence of each source string is rewritten (length prefix
    updated). With ``require_all`` (default) a source string that matches
    nothing raises — the typo guard cloning workflows want.
    """
    for old, new in mapping.items():
        if not old:
            raise EntityStringError("empty source string")
        try:
            new.encode("ascii")
        except UnicodeEncodeError:
            raise EntityStringError(
                f"replacement {new!r} is not ASCII — engine identifiers/paths "
                f"must stay ASCII") from None

    cf = cooked.parse(cooked_bytes)
    hits = {old: 0 for old in mapping}
    for sec in cf.sections:
        payload = sec.payload
        sites = _scan_payload(payload)
        # Rebuild back-to-front so earlier offsets stay valid.
        for off, s in reversed(sites):
            new = mapping.get(s)
            if new is None:
                continue
            enc = new.encode("ascii")
            tail = off + 4 + len(s.encode("ascii"))
            payload = (payload[:off] + struct.pack("<I", len(enc)) + enc
                       + payload[tail:])
            hits[s] += 1
        sec.payload = payload

    if require_all:
        missing = sorted(o for o, c in hits.items() if c == 0)
        if missing:
            raise EntityStringError(
                f"string(s) not present in entity: {', '.join(missing)}")
    return cooked.emit(cf)
