"""Clone a vanilla magical-object cooked entity into a new, distinct item.

This is the conservative first item "cooker": it performs **length-preserving**
byte edits only. Every replacement keeps the original byte length, so the
cooked container framing (BEGIN/END markers, per-section lengths) is untouched
and the result is guaranteed byte-compatible with what the engine already
accepts. Variable-length field edits (which require re-emitting the container
and have unproven engine tolerance) are intentionally out of scope here.

Supported edits:
  * :func:`rename_id` — rename the item id across every internal scoped node
    name (``[Value] <id>\\...``) and text-bank key (``<id>_Name`` ...), so the
    clone is a fully independent resource that won't collide with the base.
  * :func:`replace_lstr` — repoint a length-prefixed string (icon path, debug
    name, text key) to an equal-length replacement, anchored on its ``<u32
    len><bytes>`` prefix so it can't hit an unrelated substring.

The id of a magical object is the entity filename stem (e.g. ``Armor_Per_Object``)
and appears verbatim inside the cooked bytes wherever the engine scopes a node
or text key to that item. A plain byte replace of the id token therefore renames
every reference at once — valid precisely because we require equal length.
"""

from __future__ import annotations

import hashlib
import struct
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

#: Container framing markers — 16-byte GUID candidates that contain these are
#: section brackets, not node identities, and must never be treated as GUIDs.
_MARKERS = (b"\x11\x11\xbb\xaa", b"\x22\x22\xbb\xaa")


def _require_same_len(old: bytes, new: bytes, what: str) -> None:
    if len(old) != len(new):
        raise ValueError(
            f"{what}: replacement must keep byte length "
            f"({old!r}={len(old)}B vs {new!r}={len(new)}B). The length-preserving "
            f"cooker cannot change framing; pad/trim the value or add a "
            f"variable-length cooker."
        )


def _rewrite_id_in_lstrings(payload: bytes, ob: bytes, nb: bytes) -> bytes:
    """Replace ``ob``->``nb`` inside every length-prefixed string of a section
    payload, fixing each string's u32 length prefix. Non-string bytes (GUIDs,
    floats, markers) pass through verbatim, so when ``len(ob)==len(nb)`` the
    output is byte-identical and when it differs only id-bearing string slots
    grow/shrink.
    """
    out = bytearray()
    n = len(payload)
    i = 0
    while i + 4 <= n:
        ln = struct.unpack_from("<I", payload, i)[0]
        if 3 <= ln <= 4096 and i + 4 + ln <= n:
            chunk = payload[i + 4: i + 4 + ln]
            if all(0x20 <= b < 0x7f for b in chunk):
                if ob in chunk:
                    chunk = chunk.replace(ob, nb)
                    out += struct.pack("<I", len(chunk)) + chunk
                else:
                    out += payload[i: i + 4 + ln]
                i += 4 + ln
                continue
        out += payload[i: i + 1]
        i += 1
    out += payload[i:]
    return bytes(out)


def rename_id(data: bytes, base_id: str, new_id: str) -> bytes:
    """Rename the item id everywhere it appears in the cooked bytes.

    Renames internal scoped node names and text-bank keys in one pass (they all
    embed the id token). When the new id is the same byte length this is a plain
    length-preserving replace; when it differs, the cooked container is parsed
    and each section's length-prefixed strings are rewritten with corrected
    prefixes, then re-emitted (sections are marker-delimited, so the framing
    stays valid regardless of size change).
    """
    ob, nb = base_id.encode("utf-8"), new_id.encode("utf-8")
    if ob not in data:
        raise ValueError(f"item id {base_id!r} not found in cooked bytes")
    if len(ob) == len(nb):
        return data.replace(ob, nb)
    from . import cooked
    cf = cooked.parse(data)
    for sec in cf.sections:
        sec.payload = _rewrite_id_in_lstrings(sec.payload, ob, nb)
    return cooked.emit(cf)


def replace_lstr(data: bytes, old: str, new: str, *, what: str = "string") -> bytes:
    """Replace a length-prefixed string ``<u32 len><bytes>`` in place.

    Anchored on the 4-byte little-endian length prefix so it matches a real
    cooked string slot, not an incidental substring. Length-preserving.
    """
    ob, nb = old.encode("utf-8"), new.encode("utf-8")
    _require_same_len(ob, nb, what)
    pat = struct.pack("<I", len(ob)) + ob
    rep = struct.pack("<I", len(nb)) + nb
    if pat not in data:
        raise ValueError(f"{what}: {old!r} not found as a length-prefixed string")
    return data.replace(pat, rep)


def set_value_after_label(data: bytes, label: str, old_value: float,
                          new_value: float, *, within: int = 64) -> bytes:
    """Patch a node's f32 value, anchored on its label + current value.

    A magical-object effect magnitude is stored as a little-endian f32 a few
    bytes after the value node's label string (e.g. ``Armor per Object Value``
    holds ``2.0``). We find ``<u32 len><label>`` then, within the next
    ``within`` bytes, the exact 4-byte encoding of ``old_value`` and overwrite
    it with ``new_value``. Anchoring on both the label and the expected old
    value makes the match unambiguous; the edit is 4->4 bytes so framing is
    untouched. Raises if the label or the expected value isn't found.
    """
    lb = label.encode("utf-8")
    pat = struct.pack("<I", len(lb)) + lb
    at = data.find(pat)
    if at < 0:
        raise ValueError(f"value label {label!r} not found")
    region_start = at + len(pat)
    region = data[region_start: region_start + within]
    old_bytes = struct.pack("<f", old_value)
    k = region.find(old_bytes)
    if k < 0:
        raise ValueError(
            f"{label!r}: expected value {old_value!r} not found within "
            f"{within} bytes after the label (wrong base value?)"
        )
    abs_off = region_start + k
    return data[:abs_off] + struct.pack("<f", new_value) + data[abs_off + 4:]


def find_lstrings(data: bytes, *, contains: str | None = None,
                  min_len: int = 3, max_len: int = 256) -> list[tuple[int, str]]:
    """Heuristically list length-prefixed printable strings in cooked bytes.

    For inspection/authoring only (e.g. discovering the icon path or debug
    name to repoint). Returns ``(offset_of_prefix, text)``. A slot qualifies
    when the u32 length is in ``[min_len, max_len]`` and the bytes are all
    printable ASCII. False positives are possible; verify before editing.
    """
    out: list[tuple[int, str]] = []
    n = len(data)
    i = 0
    while i + 4 <= n:
        ln = struct.unpack_from("<I", data, i)[0]
        if min_len <= ln <= max_len and i + 4 + ln <= n:
            chunk = data[i + 4: i + 4 + ln]
            if all(0x20 <= b < 0x7f for b in chunk):
                text = chunk.decode("ascii")
                if contains is None or contains in text:
                    out.append((i, text))
                i += 4 + ln
                continue
        i += 1
    return out


def _candidate_node_guids(data: bytes) -> list[bytes]:
    """Heuristically collect 16-byte node-identity GUIDs from cooked bytes.

    A cooked node is laid out as ``<16-byte GUID><u32 namelen><name>``; we
    anchor on each length-prefixed printable string and take the 16 bytes
    immediately before its length prefix. Candidates that are all-zero (empty
    refs) or contain a framing marker (i.e. we grabbed a bracket, not a GUID)
    are dropped. Order-preserving with duplicates so callers can dedupe.
    """
    out: list[bytes] = []
    n = len(data)
    i = 0
    while i + 4 <= n:
        ln = struct.unpack_from("<I", data, i)[0]
        if 3 <= ln <= 200 and i + 4 + ln <= n:
            chunk = data[i + 4: i + 4 + ln]
            if all(0x20 <= b < 0x7f for b in chunk):
                if i >= 16:
                    g = data[i - 16: i]
                    if g != b"\x00" * 16 and not any(m in g for m in _MARKERS):
                        out.append(g)
                i += 4 + ln
                continue
        i += 1
    return out


def own_node_guids(cooked: bytes, corpus: list[bytes]) -> list[bytes]:
    """Return the GUIDs that uniquely identify *this* item's own nodes.

    ``corpus`` is the raw bytes of every sibling magical-object entity (the
    vanilla item set). A GUID that appears in only this item is its own node
    identity and must be re-minted when cloning; a GUID shared across items is
    a class-table entry or a template/inherited node reference and is left
    untouched so external links keep resolving.
    """
    seen: dict[bytes, int] = defaultdict(int)
    for raw in corpus:
        for g in set(_candidate_node_guids(raw)):
            seen[g] += 1
    mine = _candidate_node_guids(cooked)
    # corpus is expected to include `cooked` itself; "own" == appears in
    # exactly one item. If the caller forgot to include it, count==0 also
    # means own.
    own: list[bytes] = []
    for g in dict.fromkeys(mine):  # de-dupe, keep order
        if seen.get(g, 0) <= 1:
            own.append(g)
    return own


def _mint_guid(old: bytes, salt: bytes) -> bytes:
    """Deterministically derive a fresh 16-byte GUID from an old one + salt.

    Deterministic so re-cooking the same item is reproducible (stable bytes,
    stable backups). The salt is the new item id, so two different clones of
    the same base get different identities.
    """
    return hashlib.sha256(salt + old).digest()[:16]


def remint_guids(cooked: bytes, corpus: list[bytes], salt: str) -> bytes:
    """Give every own node of ``cooked`` a fresh identity GUID.

    Each own GUID is replaced everywhere it occurs (definition AND any internal
    references), so cross-links inside the item stay consistent. 16->16 bytes,
    so framing is untouched. ``salt`` is the new item id. Shared/external GUIDs
    are preserved. Returns the re-minted bytes.
    """
    own = own_node_guids(cooked, corpus)
    salt_b = salt.encode("utf-8")
    out = cooked
    for g in own:
        out = out.replace(g, _mint_guid(g, salt_b))
    return out


def load_corpus(corpus_dir: Path) -> list[bytes]:
    """Read every cooked magical-object entity under ``corpus_dir`` (recursively)
    as raw bytes, for use as the sibling corpus in :func:`own_node_guids`."""
    return [p.read_bytes()
            for p in sorted(corpus_dir.rglob("*.EntitySettingsResource.gen"))]


#: Decoded path of the magical-objects text bank (base = keys file).
MAGIC_TEXT_BANK = "Text/Magical_Objects~GAM.xls.LocalText.gen"


def build_magic_item(
    *,
    new_id: str,
    base_id: str,
    base_cooked: bytes,
    corpus: list[bytes],
    rarity: str = "Common",
    name: str | None = None,
    description: str | None = None,
    value_patches: list[tuple[str, float, float]] | None = None,
    bank_base_gen: Path | None = None,
) -> dict[str, bytes]:
    """Produce every file a new, distinct, named magical object needs.

    Returns ``{decoded_path: cooked_bytes}`` ready to drop into a mod's
    ``assets/`` tree (the apply layer registers + installs them). Pieces:

    * the cloned entity at
      ``EntitySettings/Objects/Magical_Objects/<rarity>/<new_id>...gen`` with
      re-minted GUIDs (distinct identity), the id renamed, and any
      ``value_patches`` applied (each ``(label, old, new)`` f32 edit);
    * when ``name`` is given and ``bank_base_gen`` points at the live text
      bank, the bank + every language sibling with ``<new_id>_Name`` /
      ``_Description`` appended.

    ``new_id`` may be any length — :func:`rename_id` re-emits the container
    when it differs from ``base_id``.
    """
    ent = ItemEdit(base_id=base_id, new_id=new_id, corpus=corpus).apply(base_cooked)
    for label, old, new in (value_patches or []):
        ent = set_value_after_label(ent, label, old, new)

    files: dict[str, bytes] = {
        f"EntitySettings/Objects/Magical_Objects/{rarity}/"
        f"{new_id}.entity.ot.EntitySettingsResource.gen": ent
    }

    if name is not None and bank_base_gen is not None:
        from . import text_patches as T
        pairs = {f"{new_id}_Name": name}
        if description is not None:
            pairs[f"{new_id}_Description"] = description
        banks = T.append_bank_keys(bank_base_gen, pairs)
        files[MAGIC_TEXT_BANK] = banks.pop("__base__")
        for lang_tok, blob in banks.items():
            files[MAGIC_TEXT_BANK + lang_tok] = blob
    return files


@dataclass
class ItemEdit:
    """Declarative length-preserving edit set for one cloned item."""
    base_id: str
    new_id: str
    #: (old_lstr, new_lstr) pairs — icon path, debug name, etc.
    lstr_swaps: list[tuple[str, str]] = field(default_factory=list)
    #: Raw bytes of the sibling item corpus. When set, the clone's own node
    #: GUIDs are re-minted so the engine sees a distinct object (otherwise it
    #: dedupes against the base by GUID and the item never enters the pool).
    corpus: list[bytes] = field(default_factory=list)

    def apply(self, cooked: bytes) -> bytes:
        out = cooked
        if self.corpus:
            # Re-mint BEFORE the string rename so corpus GUID matching (which is
            # name-independent) is unaffected by the id swap.
            out = remint_guids(out, self.corpus, salt=self.new_id)
        out = rename_id(out, self.base_id, self.new_id)
        for old, new in self.lstr_swaps:
            # The id rename may already have rewritten the id token inside
            # these strings; rename both sides so the swap still matches.
            old2 = old.replace(self.base_id, self.new_id)
            new2 = new.replace(self.base_id, self.new_id)
            out = replace_lstr(out, old2, new2, what="lstr swap")
        return out
