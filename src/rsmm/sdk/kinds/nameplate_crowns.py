"""Experimental native crown layouts for solo and co-op development."""
from pathlib import Path

from ...engine import corpus, nameplate_crown
from ..content import ContentDef, ContentError
from ._common import validate_id


def emit(mod_id: str, defn: ContentDef, out_dir: Path) -> list[Path]:
    validate_id("nameplate_crown", defn.id)
    unknown = set(defn.fields) - {"preview", "include_peers", "width", "y"}
    if unknown:
        raise ContentError(f"nameplate_crown: unknown fields {sorted(unknown)}")
    fields = dict(defn.fields)
    include_peers = fields.pop("include_peers", False)
    if type(include_peers) is not bool:
        raise ContentError("nameplate_crown: include_peers must be boolean")
    source = corpus.read(nameplate_crown.SOURCE)
    if source is None:
        raise ContentError("nameplate_crown: installed native UI resources are unavailable")
    paths = [nameplate_crown.TARGET]
    if include_peers:
        paths.append(nameplate_crown.TARGET.replace("_Common.entity", "_Peer.entity"))
    cooked = {}
    try:
        for path in paths:
            target = corpus.read(path)
            if target is None:
                raise ContentError(f"nameplate_crown: missing installed resource {path}")
            data = nameplate_crown.add_crown(target, source, **fields)
            if data != target:
                cooked[out_dir / path] = data
    except (ValueError, UnicodeError) as error:
        raise ContentError(f"nameplate_crown: {error}") from error
    for dest, data in cooked.items():
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    return list(cooked)
