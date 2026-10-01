"""The Abilities tab: one shipped hero's abilities as numbers and a graph.

A Numbers view lists every literal an ability uses as a plain form, and a
Diagram view draws its parts and the links between them. The page builds
``[[content.abilities]]`` steps as you set values, re-point links and copy
groups. Every change re-runs the steps and the pre-apply checks here, so the
page shows the edited graph and anything the build would refuse. Nothing is
written until you save: *Save to mod* puts the steps into a custom hero's
block (``kind = "hero"``, ``base`` = this hero) in the chosen mod, in place
of the steps it had, and ``rsmm apply`` builds them. Opening that hero brings
its saved steps back, so work continues where it stopped. The page is
``pages/abilities.html``.
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


def _obj_literals(c, f) -> list[str]:
    """The literals inside object field ``f``, in the order ``set = "Part.f[n]"``
    counts them (``position``, ``transform``, a traverser's shape, ...)."""
    from rsmm.engine import entity_graph as EG
    sub = EG.Component(0, c.cls, "", "", b"", None,
                       body=c.body[f.offset:f.offset + f.size], classes=c.classes)
    return [t.text for t in EG.tokens(sub) if t.kind == "value"]


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
    orig = EG.parse(files[stem], stem).components
    was = {(c.guid.hex(), i): f.text for c in orig for i, f in enumerate(EF.fields(c))}
    was_lits = {(c.guid.hex(), i): _obj_literals(c, f) for c in orig
                for i, f in enumerate(EF.fields(c)) if f.kind == "obj" and not f.items}
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
    literal = {c.guid.hex(): f.text for c in g.components if c.cls == "oCEntityCpntValueSettings"
               for f in EF.fields(c) if f.name == "value" and "<-" not in f.text}
    comps = []
    for c in g.components:
        fields = []
        for i, f in enumerate(EF.fields(c)):
            links = (_field_targets(c, f, picker) if f.kind in ("ref", "ref[]", "value")
                     else [])
            old = was.get((c.guid.hex(), i))
            row = {
                "name": f.name, "kind": f.kind, "text": f.text,
                "targets": [g for g, _p in links], "paths": [p for _g, p in links],
                "items": len(f.items),
                "was": old if old is not None and old != f.text else None,
            }
            if f.kind == "value" and links:
                # A linked number's inline literal is dead; what the game reads
                # is the source's, known here when the source is a plain Value.
                row["source"] = literal.get(links[0][0])
            elif f.kind == "obj" and not f.items:
                row["lits"] = _obj_literals(c, f)
                row["wasLits"] = was_lits.get((c.guid.hex(), i))
            fields.append(row)
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


def _manifest(req: Request, mod_id: str):
    from rsmm.cli.editor import content as C
    if not C._MOD_ID_RE.match(mod_id):
        raise ValueError("a mod id takes letters, digits, - and _ only")
    path = req.ctx.mods_dir / mod_id / "manifest.toml"
    if not path.is_file():
        raise ValueError(f"no mod {mod_id!r}")
    return path


def _bases(hero: str) -> set[str]:
    """The ``base`` spellings a hero block may use for ``hero``: its folder
    name (``SunWukong``) or its herodef (``Sun_Wukong``)."""
    from rsmm.cli.editor import content as C
    return {hero, C._herodefs().get(hero, hero)}


def _mods(req: Request) -> dict:
    from rsmm.cli.editor.content import list_mods
    return {"mods": list_mods(req.ctx.mods_dir)}


def _hero_blocks(req: Request) -> dict:
    """The mod's custom heroes built on ``hero``, with their saved steps."""
    from rsmm.cli.editor import modio
    path = _manifest(req, req.arg("mod"))
    bases = _bases(req.arg("hero"))
    blocks = modio.hero_blocks(path.read_text(encoding="utf-8"))
    return {"blocks": [b for b in blocks if b["base"] in bases],
            "others": sorted({b["base"] for b in blocks if b["base"] not in bases})}


def _save(req: Request) -> dict:
    from rsmm.cli.editor import modio
    steps = req.body.get("steps") or []
    if not isinstance(steps, list) or not all(isinstance(x, dict) for x in steps):
        raise ValueError("steps is a list of tables")
    hero, block = str(req.body.get("hero") or ""), str(req.body.get("block") or "")
    path = _manifest(req, str(req.body.get("mod") or ""))
    text = path.read_text(encoding="utf-8")
    match = [b for b in modio.hero_blocks(text) if b["id"] == block]
    if not match or match[0]["base"] not in _bases(hero):
        raise ValueError(f"{block!r} is not a custom hero built on {hero}")
    # The steps must still build on this hero before they are written.
    if steps and graph_payload(hero, steps)["error"]:
        raise ValueError("the changes do not build yet; fix the step marked in red first")
    path.write_text(modio.set_hero_abilities(text, block, steps), encoding="utf-8")
    return {"saved": str(path), "steps": len(steps)}


ROUTES = {
    ("GET", "/api/heroes"): lambda req: {"heroes": _heroes()},
    ("POST", "/api/graph"): _graph,
    ("GET", "/api/mods"): _mods,
    ("GET", "/api/heroblocks"): _hero_blocks,
    ("POST", "/api/save"): _save,
}
