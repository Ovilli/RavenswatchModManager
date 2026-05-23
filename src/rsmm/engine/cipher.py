"""Shared cipher tables for Ravenswatch's asset-name obfuscation.

The game stores cooked assets under DarkTalesResources/_Cooking/<encoded>;
the engine encodes the logical (decoded) path through a per-character
substitution before opening the file. tools/find_iyg.py reverse-engineered
the *decoding* tables — this module exposes both directions.

Note: the LOWER and UPPER tables are NOT bijective. Two encoded letters
can decode to the same decoded letter (e.g. encoded 'e' and 'k' both
decode to lowercase 'v'). When that happens we pick the encoded letter
that appears in observed game paths most often — which is the inverse
that the game's encoder actually emits. The mapping below was derived by
encoding known plaintext paths and confirming against UsedRscList.ot.
"""

from __future__ import annotations

# Forward (encoded -> decoded), from tools/find_iyg.py.
LOWER_DECODE = {
    'a': 'b', 'b': 'c', 'c': 'j', 'd': 'i', 'e': 'v', 'f': 'q', 'g': 'a',
    'h': 'f', 'i': 't', 'j': 'p', 'k': 'v', 'l': 'l', 'm': 'k', 'n': 'h',
    'o': 'w', 'p': 'x', 'q': 'e', 'r': 'o', 's': 'y', 't': 'd', 'u': 'r',
    'v': 's', 'w': 'u', 'x': 'm', 'y': 'g', 'z': 'n',
}
UPPER_DECODE = {
    'A': 'H', 'B': 'B', 'C': 'Y', 'D': 'V', 'E': 'J', 'F': 'S', 'G': 'L',
    'H': 'M', 'I': 'K', 'J': 'U', 'K': 'G', 'L': 'R', 'M': 'E', 'N': 'D',
    'O': 'O', 'P': 'Q', 'Q': 'T', 'R': 'W', 'S': 'C', 'T': 'P', 'U': 'N',
    'V': 'F', 'W': 'A', 'X': 'I', 'Y': 'Y', 'Z': 'I',
}
SYMBOL_DECODE = {'!': '\\'}

# Inverse (decoded -> encoded). Where two encoded letters share a decoded
# value, the lower-alphabet inverse is the one the engine emits.
# Manually picked from collisions: decoded 'v' <- encoded 'e' (not 'k'),
# decoded 'Y' <- encoded 'C' (not 'Y'), decoded 'I' <- encoded 'X'
# (not 'Z') — all verified against real cooked paths.
LOWER_ENCODE = {
    'b': 'a', 'c': 'b', 'j': 'c', 'i': 'd', 'v': 'e', 'q': 'f', 'a': 'g',
    'f': 'h', 't': 'i', 'p': 'j', 'k': 'm', 'l': 'l', 'h': 'n', 'w': 'o',
    'x': 'p', 'e': 'q', 'o': 'r', 'y': 's', 'd': 't', 'r': 'u', 's': 'v',
    'u': 'w', 'm': 'x', 'g': 'y', 'n': 'z',
}
UPPER_ENCODE = {
    'H': 'A', 'B': 'B', 'Y': 'C', 'V': 'D', 'J': 'E', 'S': 'F', 'L': 'G',
    'M': 'H', 'K': 'I', 'U': 'J', 'G': 'K', 'R': 'L', 'E': 'M', 'D': 'N',
    'O': 'O', 'Q': 'P', 'T': 'Q', 'W': 'R', 'C': 'S', 'P': 'T', 'N': 'U',
    'F': 'V', 'A': 'W', 'I': 'X',
}
# Note: `!` in encoded names is the on-disk substitute for `\` when a
# path is collapsed past directory-depth-2 into a single filename
# (see asset_map.json — third+ level directories become "X!Y" inside the
# filename). For top-level 1- and 2-deep paths, `\` passes through
# unchanged. There is intentionally no SYMBOL_ENCODE table; the caller
# is expected to encode at the per-component level if collapsing is
# needed, so `encode()` below has no symbol branch.


def decode(s: str) -> str:
    out = []
    for c in s:
        if c in SYMBOL_DECODE:
            out.append(SYMBOL_DECODE[c])
        elif c.isupper() and c in UPPER_DECODE:
            out.append(UPPER_DECODE[c])
        elif c.islower() and c in LOWER_DECODE:
            out.append(LOWER_DECODE[c])
        else:
            out.append(c)
    return ''.join(out)


def encode(s: str) -> str:
    out = []
    for c in s:
        if c.isupper() and c in UPPER_ENCODE:
            out.append(UPPER_ENCODE[c])
        elif c.islower() and c in LOWER_ENCODE:
            out.append(LOWER_ENCODE[c])
        else:
            out.append(c)
    return ''.join(out)


# Self-test: a few round-trips that must hold.
def _selftest() -> None:
    cases = [
        ("EntitySettings", "MzidisFqiidzyv"),
        ("Book_Menu", "Brrm_Hqzw"),
        ("Social", "Frbdgl"),
        ("Book_Social_Tab_Mesh_Controller.entity.ot.EntitySettingsResource.gen",
         "Brrm_Frbdgl_Qga_Hqvn_Srziurllqu.qzidis.ri.MzidisFqiidzyvLqvrwubq.yqz"),
    ]
    for dec, enc in cases:
        assert encode(dec) == enc, f"encode({dec!r}) -> {encode(dec)!r}, expected {enc!r}"
        assert decode(enc) == dec, f"decode({enc!r}) -> {decode(enc)!r}, expected {dec!r}"


if __name__ == "__main__":
    _selftest()
    print("cipher.py self-test OK")
