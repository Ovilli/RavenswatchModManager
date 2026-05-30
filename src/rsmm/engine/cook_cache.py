"""Apply-time auto-cook for source-format mod assets.

Mod folders may contain either:
  * pre-cooked binary files mirroring the decoded path
    (e.g. `mods/MyMod/Hero/Romeo/MeshTextured.tpi`), or
  * editable source-format files
    (e.g. `mods/MyMod/Hero/Romeo/MeshTextured.dds`).

`maybe_cook(src, decoded)` is the single hook into apply-mods. It returns
the path that should actually be copied to the game install:

  - pre-cooked input  -> returned unchanged
  - source-format input -> cooked through the per-class encoder, cached
                           under `<repo>/.rsmm/cook_cache/<sha256>.<ext>`,
                           and the cache path returned

The cache is keyed by sha256(src_bytes) so an unchanged source skips re-cook
on every apply. Cache lifetime is per-repo; safe to delete.

Encoders are not yet implemented for most classes — calling `maybe_cook`
on a source-format file with an unreversed schema raises NotReversedError
with a pointer to docs/RE_NOTES.md.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from . import cooked, cooked_schemas
from .paths import REPO_ROOT

# Source extension -> cooked-asset class name. Authoritative mapping for the
# "what should this become when cooked?" question. Cooked / encoded variants
# of the same file (.yqz, .tpi, .zux, .gen, .dxt, .nrm) are pre-cooked and
# excluded here.
SOURCE_EXT_CLASS: dict[str, str] = {
    ".gltf": "oCGeometry",
    ".glb": "oCGeometry",
    ".dds": "oCTexture",
    ".png": "oCTexture",
    ".tga": "oCTexture",
    ".material.json": "oCMaterial",
    ".skeleton.json": "oCSkeleton",
    ".anim.gltf": "oCAnimation",
}

# Cooked / encoded extensions — passthrough unchanged.
COOKED_EXTS: frozenset[str] = frozenset({
    ".yqz", ".tpi", ".zux",         # encoded
    ".gen", ".dxt", ".nrm",         # decoded variants
    ".ot",                          # uncooked text source (engine reads either)
})

# Content magic -> cooked class. A mod asset is most naturally named after
# the *cooked* file it overrides (so it matches `asset_map.json`), e.g.
# `Juliet_GEO.fbx.Geometry.gen`, while its bytes are actually a source
# format (glTF/PNG/DDS). Sniffing the magic lets such a file both match the
# asset map and still get cooked, regardless of its extension.
_MAGIC_CLASS: list[tuple[bytes, str]] = [
    (b"glTF", "oCGeometry"),
    (b"\x89PNG\r\n\x1a\n", "oCTexture"),
    (b"DDS ", "oCTexture"),
]


def _class_by_magic(src_bytes: bytes) -> str | None:
    for magic, cls in _MAGIC_CLASS:
        if src_bytes.startswith(magic):
            return cls
    return None


def _cache_dir() -> Path:
    d = REPO_ROOT / ".rsmm" / "cook_cache"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _source_class(src: Path) -> str | None:
    """Resolve a source file path to its target cooked class, if any.

    Multi-segment extensions (.material.json, .anim.gltf) are matched first;
    fall back to single-segment for the common case.
    """
    name = src.name.lower()
    for ext, cls in SOURCE_EXT_CLASS.items():
        if name.endswith(ext) and ext.count(".") > 1:
            return cls
    return SOURCE_EXT_CLASS.get(src.suffix.lower())


def _sniff_magic(src: Path) -> bytes:
    try:
        with open(src, "rb") as fh:
            return fh.read(8)
    except OSError:
        return b""


def is_source(src: Path) -> bool:
    """True if `src` looks like a source-format file that needs cooking.

    Content magic wins over the extension, so a mod asset named after the
    cooked file it overrides (e.g. `*.Geometry.gen`) but holding glTF/PNG/
    DDS bytes is still recognised as a source that needs cooking.
    """
    if _class_by_magic(_sniff_magic(src)) is not None:
        return True
    if src.suffix.lower() in COOKED_EXTS:
        return False
    return _source_class(src) is not None


#: Sidecar file (next to a custom mesh) carrying its orientation transform.
COOK_SIDECAR_SUFFIX = ".rsmmcook"


def _read_cook_sidecar(src: Path) -> tuple[dict | None, bytes]:
    """Load `<src>.rsmmcook` (JSON) if present: returns (transform, raw_bytes).

    Authored by `sdk.Mod().model(..., rotate_deg=...)`. Raw bytes are folded
    into the cook-cache key so changing the transform re-cooks.
    """
    import json

    sidecar = src.with_name(src.name + COOK_SIDECAR_SUFFIX)
    if not sidecar.exists():
        return None, b""
    raw = sidecar.read_bytes()
    try:
        return json.loads(raw), raw
    except (ValueError, UnicodeDecodeError):
        return None, b""


def maybe_cook(src: Path, template: Path | None = None) -> Path:
    """Return the path that should be copied to the game install for `src`.

    Pre-cooked inputs are returned unchanged. Source-format inputs are
    cooked once per content hash and cached. Raises NotReversedError when
    the target class has no encoder registered yet.

    `template`, when given, is the game's current cooked file at the
    destination. A custom `.glb` mesh (no embedded cooked bytes) is cooked
    by swapping its geometry into that template — the only way to build a
    structurally valid cooked mesh without a full oCGeometry writer.
    """
    src_bytes = src.read_bytes()
    # Magic wins over extension (see is_source): a `*.Geometry.gen`-named
    # file holding glTF bytes is a custom mesh to cook, not a cooked file.
    cls = _class_by_magic(src_bytes) or _source_class(src)
    if cls is None:
        return src
    if _class_by_magic(src_bytes) is None and src.suffix.lower() in COOKED_EXTS:
        return src

    # Mesh cooking. A glTF mesh is cooked by swapping its geometry into a
    # cooked *template*. The template is, in order of preference:
    #   1. the original cooked bytes embedded by `rsmm uncook` (extras), used
    #      when the reference mesh was edited — it's already in template space;
    #   2. the game's current cooked file at the destination, for a mesh with
    #      no embedded original (a fully fresh custom mesh).
    # An *unedited* uncook GLB round-trips byte-exact (no swap).
    if cls == "oCGeometry" and src_bytes[:4] == b"glTF":
        from .geometry_cook import (
            ENCODER_VERSION,
            geometry_matches_cooked,
            swap_geometry,
            template_from_uncooked_glb,
        )

        try:
            embedded = template_from_uncooked_glb(src_bytes)
        except ValueError:
            embedded = None

        if embedded is not None and geometry_matches_cooked(src_bytes, embedded):
            # Untouched uncook GLB -> return the original cooked bytes verbatim.
            sha = hashlib.sha256(src_bytes).hexdigest()
            cache_path = _cache_dir() / f"{sha}.yqz"
            if not cache_path.exists():
                cache_path.write_bytes(embedded)
            return cache_path

        if embedded is not None:
            tpl_bytes = embedded
        elif template is not None and template.exists():
            tpl_bytes = template.read_bytes()
        else:
            raise cooked_schemas.NotReversedError(
                "oCGeometry",
                "cooking a custom mesh needs a template: either embed the "
                "original via `rsmm uncook`, or apply against an installed "
                "game file",
            )

        transform, tf_bytes = _read_cook_sidecar(src)
        # Fold encoder version + transform into the key so an encoder fix or
        # an orientation tweak invalidates any older cached cooked file.
        key = hashlib.sha256(
            f"geom{ENCODER_VERSION}".encode() + tf_bytes
            + src_bytes + hashlib.sha256(tpl_bytes).digest()).hexdigest()
        cache_path = _cache_dir() / f"{key}.yqz"
        if not cache_path.exists():
            cache_path.write_bytes(
                swap_geometry(tpl_bytes, src_bytes, transform=transform))
        return cache_path

    sha = hashlib.sha256(src_bytes).hexdigest()
    cache_path = _cache_dir() / f"{sha}.yqz"
    if cache_path.exists():
        return cache_path

    handler = cooked_schemas.get(cls)

    # Prefer handler.encode_container when present — it builds the full
    # cooked-file byte string with the correct class table + sections for
    # this asset type (e.g. oCTexture needs a variant-B container with
    # oIResource + oISerializable parent classes and a 2-section split).
    if hasattr(handler, "encode_container"):
        cache_path.write_bytes(handler.encode_container(src_bytes))
        return cache_path

    payload = handler.encode(src_bytes)

    # Generic fallback for classes that haven't published a container
    # builder yet. Single-section variant-A wrapper.
    cf = cooked.CookedFile(
        variant="A",
        hdr_a=0x10,
        flags=0x01,
        extra=0x01,
        type_tag=cooked.DEFAULT_TYPE_TAG,
        classes=[cooked.ClassDef(name=cls, class_id=0, version_major=0,
                                 version_minor=0, parent_id=0)],
        sections=[cooked.Section(payload=payload)],
    )
    cache_path.write_bytes(cooked.emit(cf))
    return cache_path
