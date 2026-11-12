"""Experimental native crown layout; runtime host selection is not implemented."""
from pathlib import Path

from ...engine import corpus, nameplate_crown
from ..content import ContentDef, ContentError
from ._common import validate_id


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    validate_id("nameplate_crown", defn.id)
    unknown = set(defn.fields) - {"preview", "width", "y"}
    if unknown:
        raise ContentError(f"nameplate_crown: unknown fields {sorted(unknown)}")
    target, source = corpus.read(nameplate_crown.TARGET), corpus.read(nameplate_crown.SOURCE)
    if target is None or source is None:
        raise ContentError("nameplate_crown: installed native UI resources are unavailable")
    try:
        data = nameplate_crown.add_crown(target, source, **defn.fields)
    except (ValueError, UnicodeError) as error:
        raise ContentError(f"nameplate_crown: {error}") from error
    dest = out_dir / nameplate_crown.TARGET
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return [dest]
