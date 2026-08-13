"""**Mesh** content builder — put the mod's model in place of a shipped one.

The smallest possible custom-art change: cook a ``.glb`` and write it over a
vanilla mesh's cooked path. Every entity, material, texture, level, tile and
cache in the game keeps referring to the same resource name, so nothing else
has to move — this is a texture-style override that happens to carry geometry.

.. code-block:: toml

    [[content]]
    kind   = "mesh"
    id     = "shrine_over_ruin_block"
    target = "Scenery\\\\DarkHills\\\\Wall_Ruins_Block_Small_A.fbx"
    model  = "art/shrine.glb"

``target`` (str, required)
    Reference form of the shipped mesh to replace. Everything that places it
    now shows the mod's shape instead — including every other tile that uses
    it, which is the trade for needing no new asset at all.
``model`` (str, required)
    Path, relative to the mod root, of the ``.glb`` to cook. The mod ships it.

The cooked container is grafted onto the **target's own** cooked bytes, so the
result keeps the vertex formats, material slots and submesh framing the engine
already expects from that resource (:func:`rsmm.engine.prop_cook.cook_model`).
``transform`` is accepted and forwarded for orientation/scale fixes.

``transform.skin`` (``"transfer"`` default, or ``"rigid"``)
    How the model is bound to the target's skeleton, and the setting that
    decides whether replacing a **character** works at all.

    ``transfer`` rebuilds per-vertex weights from the nearest vertices of the
    mesh being replaced. That is right for a prop or a same-shaped body, and
    wrong for a different body: it assumes the custom mesh occupies roughly
    the same space as the original, so when the limbs are somewhere else each
    vertex binds to whatever bone happened to be nearest and the model is torn
    apart on the first animation frame.

    ``rigid`` binds every vertex to a single bone — the one owning the
    template vertex closest to the template's centre, i.e. a spine or pelvis
    on a humanoid. The model then follows the character intact and never
    deforms. Limbs will not bend; that is the trade, and for a replacement
    body it is the difference between a usable model and a shredded one.

Compared with ``poi``'s ``prop`` block this cooks exactly one asset and
introduces no new resource name, which is also what makes it the way to test a
custom mesh in isolation: if a `prop` misbehaves, pointing a `mesh` at the same
model says whether the geometry cook or the entity cook is at fault.

Confidence: ``experimental`` — the cook is the same one ``prop`` uses and the
override path is the ordinary asset-replacement mechanism, but a mod-supplied
mesh has not yet been confirmed rendering in-game.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from ...engine import prop_cook as PC
from ..content import ContentDef, ContentError

_log = logging.getLogger(__name__)

_ID_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")

#: Folder under a mod root that holds convention-discovered meshes.
MESHES_DIRNAME = "meshes"


def _mod_source(out_dir: Path, rel: str, defn_id: str, field: str) -> Path:
    """Resolve a source path the manifest gave, relative to the mod root.

    ``out_dir`` is the mod's ``assets/`` directory; source art lives outside it
    so a raw ``.glb`` is never mistaken for a cooked override and copied into
    the game install.
    """
    if not isinstance(rel, str) or not rel:
        raise ContentError(f"mesh {defn_id}: {field} must be a path, got {rel!r}")
    clean = rel.replace("\\", "/")
    if ".." in clean.split("/"):
        raise ContentError(f"mesh {defn_id}: {field} may not escape the mod ({rel!r})")
    for root in (out_dir.parent, out_dir):
        p = root / Path(*clean.split("/"))
        if p.is_file():
            return p
    raise ContentError(
        f"mesh {defn_id}: {field} {rel!r} is not in this mod — expected it at "
        f"{(out_dir.parent / clean)}. Ship the source art with the mod."
    )


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    """Cook ``model`` over ``target``'s cooked path. One file, no new names."""
    from ...engine.paths import DATA_DIR

    if not _ID_RE.match(defn.id):
        raise ContentError(f"invalid mesh id: {defn.id!r}")
    target = defn.fields.get("target")
    model = defn.fields.get("model")
    for name, val in (("target", target), ("model", model)):
        if not val or not isinstance(val, str):
            raise ContentError(f"mesh {defn.id}: '{name}' is required")
    if not target.lower().endswith(".fbx"):
        raise ContentError(
            f"mesh {defn.id}: target must be a mesh reference ending in .fbx, "
            f"got {target!r}"
        )

    # The graft template is the target's OWN cooked bytes: an in-place override
    # has to keep whatever framing that resource already had, or every existing
    # reference to it is reading a container it did not expect. `poi` already
    # solves finding it (the corpus mirrors geometry as GLB carrying the cooked
    # bytes in `extras.rsmm.cooked_b64`, not as a `.Geometry.gen`).
    from .poi import _donor_geometry

    cooked_rel = PC.art_cooked_path(target)
    template = _donor_geometry(target, defn.id)

    src = _mod_source(out_dir, model, defn.id, "model")
    dest = out_dir / Path(*cooked_rel.split("/"))
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(PC.cook_model(src.read_bytes(), template,
                                   transform=defn.fields.get("transform")))
    _log.info("mesh %s/%s: %s -> %s (in-place override)",
              mod_id, defn.id, model, target)
    return [dest]
