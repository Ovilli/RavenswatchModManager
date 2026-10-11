"""**Animation** content builder — play the mod's animation in place of a shipped clip.

The animation counterpart of ``mesh``: cook a glTF animation and write it over
a shipped clip's cooked path, so every animation player that references that
clip plays the mod's motion instead.

.. code-block:: toml

    [[content]]
    kind   = "animation"
    id     = "piper_dash"
    target = "Characters\\\\Heroes\\\\Piper\\\\Animations\\\\Piper_Dash_Default.fbx"
    source = "anims/piper_dash.glb"

``target`` (str, required)
    Reference form of the shipped clip to replace (``rsmm uncook`` / the mirror
    names them ``3D/<target>.glb``).
``source`` (str, required)
    Path, relative to the mod root, of the ``.glb`` whose animation is cooked.
    Bones are matched by name, so animate the game's own bone names: the
    easiest start is the clip ``rsmm uncook`` exported, edited in Blender.
``clip`` (str, optional)
    Which glTF animation to take when the file holds several (default: first).
``strict`` (bool, optional)
    Fail when the glTF leaves a bone of the target unanimated, instead of
    holding that bone at the target's first key.

The target clip is the TEMPLATE: it supplies the bone order and the per-clip
tail fields, so the cooked file is a valid clip for the same skeleton. The
quantizers are proven against all 2240 shipped clips (cook of an exported,
unedited clip is byte-identical); see :mod:`rsmm.engine.anim_cook`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from ...engine import anim_cook as AK
from ...engine import cooked, corpus
from ..content import ContentDef, ContentError, SchemaNotMined
from . import _common as C
from .meshes import _mod_source

_log = logging.getLogger(__name__)


def cooked_path(target: str) -> str:
    """``Characters\\X\\Y.fbx`` -> ``3D/Characters/X/Y.fbx.Animation.gen``."""
    return "3D/" + target.replace("\\", "/") + ".Animation.gen"


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    C.validate_id("animation", defn.id)
    target, source = defn.fields.get("target"), defn.fields.get("source")
    for name, val in (("target", target), ("source", source)):
        if not val or not isinstance(val, str):
            raise ContentError(f"animation {defn.id}: '{name}' is required")
    if not target.lower().endswith(".fbx"):
        raise ContentError(
            f"animation {defn.id}: target must be a clip reference ending in .fbx, "
            f"got {target!r}")
    rel = cooked_path(target)
    raw = corpus.read(rel)
    if raw is None:
        raise SchemaNotMined(
            f"animation {defn.id}: no shipped clip {target!r} ({rel}) in the corpus or "
            f"the game install")
    cf = cooked.parse(raw)
    if len(cf.sections) != 2:
        raise ContentError(f"animation {defn.id}: {target} is not a 2-section oCAnimation")
    template = b"".join(s.payload for s in cf.sections)

    src = _mod_source(out_dir, source, defn.id, "source")
    try:
        payload, notes = AK.cook(src.read_bytes(), template,
                                 name=defn.fields.get("clip"),
                                 strict=bool(defn.fields.get("strict")))
    except AK.AnimCookError as e:
        raise ContentError(f"animation {defn.id}: {e}") from e
    for n in notes[:5]:
        _log.info("animation %s/%s: %s", mod_id, defn.id, n)
    if len(notes) > 5:
        _log.info("animation %s/%s: ... %d more bones held", mod_id, defn.id, len(notes) - 5)

    head = len(cf.sections[0].payload)
    cf.sections[0] = cooked.Section(payload=payload[:head])
    cf.sections[1] = cooked.Section(payload=payload[head:])
    dest = out_dir / Path(*rel.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(cooked.emit(cf))
    _log.info("animation %s/%s: %s -> %s (in-place override)", mod_id, defn.id, source, target)
    return [dest]
