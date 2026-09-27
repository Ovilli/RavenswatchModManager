"""The Abilities tab: one shipped hero's abilities as numbers and a graph.

A Numbers view lists every literal an ability uses as a plain form, and a
Diagram view draws its parts and the links between them. The page builds
``[[content.abilities]]`` steps as you set values, re-point links and copy
groups. Every change re-runs the steps and the pre-apply checks here, so the
page shows the edited graph and anything the build would refuse. Nothing is
written: the steps are copied into a custom hero's manifest (``kind = "hero"``)
and ``rsmm apply`` builds them. The page is ``pages/abilities.html``.
"""

from __future__ import annotations

import json
from functools import cache

from rsmm.cli.editor.app import Request

MOUNT = "abilities"
PAGE = "abilities.html"


@cache
def _heroes() -> list[str]:
    """Shipped heroes with a gameplay entity (``Hero_<Name>/Hero_<Name>.entity``)."""
    from rsmm.engine import corpus
    out = []
    for rel in corpus.rels("EntitySettings/Heroes/", ".EntitySettingsResource.gen"):
        parts = rel.split("/")
        if len(parts) == 4 and parts[3] == f"{parts[2]}.entity.ot.EntitySettingsResource.gen":
            out.append(parts[2].removeprefix("Hero_"))
    return sorted(set(out) - {"Common"})


@cache
def _family(hero: str) -> dict[str, bytes]:
    """Entity stem -> bytes for every entity in the hero's folder."""
    from rsmm.engine import corpus
    folder = f"Hero_{hero}"
    out = {}
    for rel in corpus.rels(f"EntitySettings/Heroes/{folder}/", ".EntitySettingsResource.gen"):
        stem = rel.rsplit("/", 1)[-1].removesuffix(".entity.ot.EntitySettingsResource.gen")
        raw = corpus.read(rel)
        if raw is not None:
            out[stem] = raw
    return out


def _field_targets(c, f, picker_cls: int) -> list[tuple[str, str]]:
    """``(target GUID hex, target path)`` for every link in field ``f``."""
    from rsmm.engine import entity_graph as EG
    body = c.body[f.offset:f.offset + f.size]
    return [(r.guid.hex(), r.path) for _o, r in EG._pickers(body, picker_cls) if r.path]


def graph_payload(hero: str, steps: list[dict], entity: str = "") -> dict:
    """What the page draws: ``hero``'s entity after ``steps``, with issues."""
    from rsmm.engine import ability_edit as AE
    from rsmm.engine import entity_fields as EF
    from rsmm.engine import entity_graph as EG

    if hero not in _heroes():
        raise ValueError(f"no shipped hero {hero!r}")
    files = _family(hero)
    main = f"Hero_{hero}"
    stem = entity or main
    if stem not in files:
        raise ValueError(f"no entity {stem!r} in {hero}'s family")
    # The unedited values, so the page can show what a change replaced. Keyed
    # by position: a part can carry two fields of one name (a selector's `mode`).
    was = {(c.guid.hex(), i): f.text
           for c in EG.parse(files[stem], stem).components
           for i, f in enumerate(EF.fields(c))}
    error, warnings = "", []
    if steps:
        try:
            res = AE.apply(files, steps, main=main, seed=f"editor:{hero}")
            files, warnings = res.files, res.warnings
        except AE.AbilityEditError as e:
            error = str(e)
    g = EG.parse(files[stem], stem)
    names = g.components[0].classes if g.components else []
    picker = names.index("oCEntityCpntPicker") if "oCEntityCpntPicker" in names else -1
    comps = []
    for c in g.components:
        fields = []
        for i, f in enumerate(EF.fields(c)):
            links = (_field_targets(c, f, picker) if f.kind in ("ref", "ref[]", "value")
                     else [])
            old = was.get((c.guid.hex(), i))
            fields.append({
                "name": f.name, "kind": f.kind, "text": f.text,
                "targets": [g for g, _p in links], "paths": [p for _g, p in links],
                "items": len(f.items),
                "was": old if old is not None and old != f.text else None,
            })
        comps.append({"id": c.guid.hex(), "name": c.name, "group": c.group,
                      "cls": c.cls.removeprefix("oCEntityCpnt").removeprefix("oCDtEntityCpnt")
                      .removesuffix("Settings"),
                      "fields": fields})
    return {"hero": hero, "entity": stem, "entities": sorted(files),
            "components": comps, "error": error, "warnings": warnings}


def steps_toml(steps: list[dict]) -> str:
    """``steps`` as ``[[content.abilities]]`` blocks."""
    out = []
    for s in steps:
        out.append("[[content.abilities]]")
        for k, v in s.items():
            out.append(f"{k} = {json.dumps(v)}")
        out.append("")
    return "\n".join(out)


# --- routes ---------------------------------------------------------------------

def _graph(req: Request) -> dict:
    steps = req.body.get("steps") or []
    if not isinstance(steps, list) or not all(isinstance(x, dict) for x in steps):
        raise ValueError("steps is a list of tables")
    out = graph_payload(str(req.body.get("hero", "")), steps, str(req.body.get("entity") or ""))
    out["toml"] = steps_toml(steps)
    return out


ROUTES = {
    ("GET", "/api/heroes"): lambda req: {"heroes": _heroes()},
    ("POST", "/api/graph"): _graph,
}
