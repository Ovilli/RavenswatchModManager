"""oCMaterial (v1.28) — handled by the generic asset-ref passthrough.

Heavily versioned (Serialize VA 0x14064c200, many migration gates) with a
variable `oCShaderParamSet` of named params whose values are not yet fully
field-typed. Rather than a stub that refuses, `oCMaterial` is registered by
`asset_refs.py` (`AssetRefsHandler`): byte-stable round-trip plus the
editable shader / texture asset references the material points at, so a mod
author can repoint a material at a different shader or texture. Deepening to
typed shader-param values (colors / floats) would move bytes out of the
opaque literal stream there.

This module intentionally does NOT register a handler — see `asset_refs`.
"""
