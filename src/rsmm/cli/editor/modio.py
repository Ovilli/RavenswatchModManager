"""A mod as the content editor reads it back, and the test-grants script.

Three jobs, all on a mod folder:

* **Test grants.** The Scripts tab writes a section of the mod's ``init.lua``
  that hands the player items, talents and XP at the start of a run, so a
  change can be tried at once instead of hoping the game offers it. The editor
  owns only the text between its two marker lines and leaves everything else
  in ``init.lua`` alone; the settings ride along as one JSON comment so the
  section can be opened again. A hero filter keeps the grants to one hero,
  because a mod's script otherwise runs for every hero (2026-10-01: a custom
  hero's test XP levelled Wukong to 4 at every run start).
* **Opening a mod.** :func:`load_mod` turns a manifest's ``item``,
  ``talent`` and ``skill`` blocks back into the page's own edit state, so a
  saved mod can be worked on again. A block the editor cannot represent
  exactly (a field it has no control for, a value the base no longer has) is
  reported and left untouched — never half-read.
* **Saving over a block.** :func:`remove_blocks` takes the opened blocks out of
  the manifest text before their new versions are appended, and proves it
  removed exactly those by parsing before and after.
"""

from __future__ import annotations

import base64
import json
import re
import tomllib
from pathlib import Path

from .content import EditorError

BEGIN = "-- >>> rsmm editor: test grants >>>"
END = "-- <<< rsmm editor: test grants <<<"
_CONFIG = "-- editor-config: "

#: Names a grant may carry into the Lua source: item ids, talent names, heroes.
_NAME_RE = re.compile(r"^[A-Za-z0-9 _'.\-]{1,64}$")
_MAX_COUNT = 99
_MAX_XP = 1_000_000


# --- test grants ---------------------------------------------------------------

def script_config(raw) -> dict:
    """``raw`` checked and normalised: ``{hero, xp, items: [{id, count}],
    talents: [{name, tier}]}``. Empty grants are dropped."""
    if not isinstance(raw, dict):
        raise EditorError("the test grants must be an object")
    hero = str(raw.get("hero") or "")
    if hero and not _NAME_RE.match(hero):
        raise EditorError(f"no hero {hero!r}")
    xp = raw.get("xp") or 0
    if isinstance(xp, bool) or not isinstance(xp, int | float) or not 0 <= xp <= _MAX_XP:
        raise EditorError(f"XP must be a whole number from 0 to {_MAX_XP}")
    items = []
    for it in raw.get("items") or []:
        iid, count = str((it or {}).get("id") or ""), (it or {}).get("count", 1)
        if not iid:
            continue
        if not _NAME_RE.match(iid):
            raise EditorError(f"no item {iid!r}")
        if isinstance(count, bool) or not isinstance(count, int) or not 1 <= count <= _MAX_COUNT:
            raise EditorError(f"{iid}: give 1 to {_MAX_COUNT} copies")
        items.append({"id": iid, "count": count})
    talents = []
    for t in raw.get("talents") or []:
        name, tier = str((t or {}).get("name") or ""), (t or {}).get("tier", 0)
        if not name:
            continue
        if not _NAME_RE.match(name):
            raise EditorError(f"no talent {name!r}")
        if isinstance(tier, bool) or tier not in (0, 1, 2, 3):
            raise EditorError(f"{name}: the rarity is 0 (Common) to 3 (Legendary)")
        talents.append({"name": name, "tier": tier})
    return {"hero": hero, "xp": int(xp), "items": items, "talents": talents}


def script_empty(cfg: dict) -> bool:
    return not (cfg["xp"] or cfg["items"] or cfg["talents"])


def _q(s: str) -> str:
    return '"' + s + '"'           # _NAME_RE leaves nothing that needs escaping


def script_lua(cfg: dict) -> str:
    """The marked ``init.lua`` section for ``cfg``."""
    items = ", ".join(f"{{ {_q(i['id'])}, {i['count']} }}" for i in cfg["items"])
    talents = ", ".join(f"{{ {_q(t['name'])}, {t['tier']} }}" for t in cfg["talents"])
    hero = _q("Hero_" + cfg["hero"]) if cfg["hero"] else "nil"
    return f"""{BEGIN}
-- Written by the rsmm editor (Scripts tab), which rewrites this section when
-- you save; your own code outside the two marker lines is left alone.
-- TESTING ONLY: a published mod should not hand out free items or XP.
{_CONFIG}{json.dumps(cfg, separators=(",", ":"))}
do
    local R = require "rsmm"
    local HERO = {hero}                 -- only for this hero; nil = every hero
    local XP = {cfg["xp"]}
    local ITEMS = {{ {items} }}         -- {{ item id, copies }}
    local TALENTS = {{ {talents} }}     -- {{ talent, rarity 0-3 }}

    if XP > 0 then R.xp.arm() end      -- before the run builds the level
    local left, talents_done, xp_tries, mine
    local function reset()
        left = {{}}
        for _, it in ipairs(ITEMS) do left[#left + 1] = {{ it[1], it[2] }} end
        talents_done, xp_tries, mine = #TALENTS == 0, XP > 0 and 0 or 5, nil
    end
    reset()
    for _, b in ipairs({{ "run:start", "run:end", "menu:enter" }}) do R.on(b, reset) end

    local function for_this_hero()
        if not HERO then return true end
        if mine == nil and R.hero.entity and R.hero.entity() then
            mine = R.hero.entity_is(HERO)
        end
        return mine == true
    end

    -- Main thread: a grant builds engine objects. One step per tick, and
    -- each counted BEFORE it runs, because a grant fires game events at once.
    R.schedule.every_main(1, function()
        if not R.entity.ready() or not for_this_hero() then return end
        if xp_tries < 5 then
            xp_tries = xp_tries + 1
            R.stat.enable_writes()
            if R.xp.grant(XP) then xp_tries = 5 end
            R.log(("[test-grants] {cfg['xp']} XP: %s"):format(
                xp_tries == 5 and "granted" or "retrying"))
        end
        if not talents_done and #R.talent.controllers() > 0 then
            talents_done = true
            for _, t in ipairs(TALENTS) do R.talent.grant(t[1], t[2]) end
        end
        local it = left[1]
        if it and R.give.ready() and R.give.count() > 0 then
            it[2] = it[2] - 1
            if it[2] <= 0 then table.remove(left, 1) end
            if not R.give.by_name(it[1]) and left[1] == it then table.remove(left, 1) end
        end
    end)
end
{END}
"""


def _region(text: str) -> tuple[int, int] | None:
    """``(start, end)`` of the editor's section in ``text``, end exclusive."""
    a = text.find(BEGIN)
    if a < 0:
        return None
    b = text.find(END, a)
    if b < 0:
        raise EditorError("init.lua has the editor's start line but not its end line; "
                          "fix it by hand")
    b += len(END)
    if text[b:b + 1] == "\n":
        b += 1
    return a, b


def read_script(init_text: str) -> dict | None:
    """The settings of the editor's section of ``init_text``, or None."""
    span = _region(init_text)
    if span is None:
        return None
    for line in init_text[span[0]:span[1]].splitlines():
        if line.startswith(_CONFIG):
            try:
                return script_config(json.loads(line[len(_CONFIG):]))
            except (ValueError, EditorError):
                break
    raise EditorError("init.lua's editor section has no readable settings; fix it by hand")


def write_script(mod_root: Path, cfg: dict) -> str:
    """Put ``cfg``'s section into ``mod_root/init.lua`` (or take it out when it
    grants nothing), leaving the rest of the file as it was. Returns what
    happened, for the page."""
    init = mod_root / "init.lua"
    old = init.read_text(encoding="utf-8") if init.is_file() else ""
    span = _region(old)
    section = "" if script_empty(cfg) else script_lua(cfg)
    if span is None:
        if not section:
            return "unchanged"
        new = (old.rstrip("\n") + "\n\n" if old.strip() else "") + section
    else:
        new = old[:span[0]] + section + old[span[1]:]
    if not new.strip():
        init.unlink(missing_ok=True)       # the file held only our section
        return "removed"
    init.write_text(new, encoding="utf-8")
    return "written"


# --- the Scripts tab's block program --------------------------------------------
# A second marked section of init.lua, beside the test grants. It carries the
# Blockly workspace state in a comment, so opening the mod puts the blocks back.

def _find(text: str, begin: str, end: str) -> tuple[int, int] | None:
    a = text.find(begin)
    if a < 0:
        return None
    b = text.find(end, a)
    if b < 0:
        raise EditorError("init.lua has the editor's block start line but not its end line; "
                          "fix it by hand")
    b += len(end)
    if text[b:b + 1] == "\n":
        b += 1
    return a, b


def read_blocks(init_text: str) -> dict | None:
    """The block program saved in ``init_text``, or None when it has none."""
    from . import blocks as B
    span = _find(init_text, B.BEGIN, B.END)
    if span is None:
        return None
    for line in init_text[span[0]:span[1]].splitlines():
        if line.startswith(B.CONFIG):
            try:
                return B.validate_state(json.loads(line[len(B.CONFIG):]))
            except (ValueError, EditorError):
                break
    raise EditorError("init.lua's block section has no readable program; fix it by hand")


def write_blocks(mod_root: Path, state) -> list[str]:
    """Put the program's section into ``mod_root/init.lua`` (or take it out when
    the program is empty), leaving the rest of the file as it was. Returns the
    warnings the page should show."""
    from . import blocks as B
    section, warnings = B.compile_blocks(state)
    init = mod_root / "init.lua"
    old = init.read_text(encoding="utf-8") if init.is_file() else ""
    span = _find(old, B.BEGIN, B.END)
    if span is None:
        if not section:
            return warnings
        new = (old.rstrip("\n") + "\n\n" if old.strip() else "") + section
    else:
        new = old[:span[0]] + section + old[span[1]:]
    if not new.strip():
        init.unlink(missing_ok=True)
    else:
        init.write_text(new, encoding="utf-8")
    return warnings


# --- saving over blocks ----------------------------------------------------------

_HEADER_RE = re.compile(r"^\s*\[\[?\s*([A-Za-z0-9_.\-]+)\s*\]\]?\s*(?:#.*)?$")


def _content(text: str) -> list:
    try:
        return [c for c in tomllib.loads(text).get("content", []) if isinstance(c, dict)]
    except tomllib.TOMLDecodeError as e:
        raise EditorError(f"manifest.toml does not parse: {e}") from e


def remove_blocks(text: str, keys: set[tuple[str, str]]) -> str:
    """``text`` without the ``[[content]]`` blocks whose ``(kind, id)`` is in
    ``keys`` (each with the comment lines directly above it). Refuses unless
    the result parses to exactly the old blocks minus those."""
    if not keys:
        return text
    lines = text.splitlines(keepends=True)
    starts = []                             # (line, is a [[content]] block)
    for i, line in enumerate(lines):
        m = _HEADER_RE.match(line)
        if m and not m.group(1).startswith("content."):
            starts.append((i, line.strip().startswith("[[") and m.group(1) == "content"))
    def attached(i: int) -> int:
        """First line of the comment run directly above line ``i``."""
        while i > 0 and lines[i - 1].lstrip().startswith("#"):
            i -= 1
        return i

    drop: set[int] = set()
    for n, (i, is_block) in enumerate(starts):
        if not is_block:
            continue
        # A block stops where the NEXT one's comment starts: that comment is
        # the next block's, and goes with it.
        end = attached(starts[n + 1][0]) if n + 1 < len(starts) else len(lines)
        body = "".join(lines[i:end])
        try:
            got = tomllib.loads(body).get("content", [{}])[0]
        except tomllib.TOMLDecodeError:
            continue
        if (got.get("kind"), got.get("id")) in keys:
            drop.update(range(attached(i), end))
    new = "".join(line for k, line in enumerate(lines) if k not in drop)
    want = [c for c in _content(text) if (c.get("kind"), c.get("id")) not in keys]
    if _content(new) != want:
        raise EditorError("could not take the opened blocks out of manifest.toml cleanly; "
                          "save to another mod, or edit it by hand")
    return re.sub(r"\n{3,}", "\n\n", new)


# --- a custom hero's ability steps (the Abilities tab) ---------------------------

#: The two blocks ability steps can live in: a custom hero (a copy of the base,
#: ``base`` names the hero) or an in-place edit of the shipped hero itself
#: (``hero`` names it). Both carry the same ``[[content.abilities]]`` steps.
ABILITY_KINDS = ("hero", "ability")


def hero_blocks(text: str, kind: str = "hero") -> list[dict]:
    """Every block of ``kind`` (``hero`` or ``ability``) with ability steps:
    ``{id, base, name, steps}`` (``base`` is the hero it is built on or edits)."""
    return [{"id": str(c.get("id") or ""), "kind": kind,
             "base": str(c.get("base") or c.get("hero") or ""),
             "name": str(c.get("name") or c.get("id") or ""),
             "steps": [s for s in c.get("abilities") or [] if isinstance(s, dict)]}
            for c in _content(text) if c.get("kind") == kind]


def add_ability_block(text: str, block_id: str, hero: str) -> str:
    """``text`` with a ``kind = "ability"`` block appended: an in-place edit of
    the shipped ``hero`` that the Abilities tab's changes can be saved into. The
    kind is experimental, so the mod is marked ``experimental = true`` (``rsmm
    lint`` fails the mod otherwise)."""
    return _append_block(_mark_experimental(text),
                         {"kind": "ability", "id": block_id, "hero": hero})


def _mark_experimental(text: str) -> str:
    """``text`` with ``experimental = true`` in its ``[mod]`` table."""
    try:
        have = tomllib.loads(text).get("mod", {}).get("experimental")
    except tomllib.TOMLDecodeError:
        return text
    if have is True:
        return text
    lines = text.splitlines(keepends=True)
    start = next((i for i, ln in enumerate(lines) if ln.strip() == "[mod]"), None)
    if start is None:
        return text
    if have is not None:                # an existing `experimental = false`
        for i in range(start + 1, len(lines)):
            if _HEADER_RE.match(lines[i]):
                break
            if re.match(r"\s*experimental\s*=", lines[i]):
                lines[i] = "experimental = true\n"
                return "".join(lines)
    end = next((i for i in range(start + 1, len(lines)) if _HEADER_RE.match(lines[i])),
               len(lines))
    while end > start + 1 and not lines[end - 1].strip():
        end -= 1                        # keep the blank line before the next table
    lines.insert(end, "experimental = true\n")
    new = "".join(lines)
    return new if tomllib.loads(new).get("mod", {}).get("experimental") is True else text


def add_hero_block(text: str, block_id: str, base: str, name: str, **extra) -> str:
    """``text`` with a ``kind = "hero"`` block appended: a clone of ``base`` that
    the Abilities tab's changes can be saved into."""
    return _append_block(text, {"kind": "hero", "id": block_id, "base": base,
                                "name": name, **extra})


def _append_block(text: str, block: dict) -> str:
    """Append ``block`` as a ``[[content]]`` table. Refuses an id this kind already
    uses, and checks the result parses to exactly the old blocks plus it."""
    from .content import _toml
    before = _content(text)
    if any(c.get("id") == block["id"] and c.get("kind") == block["kind"] for c in before):
        raise EditorError(f"manifest.toml already has a {block['kind']} block "
                          f"with id {block['id']!r}")
    new = text.rstrip("\n") + "\n\n[[content]]\n" + "".join(
        f"{k} = {_toml(v)}\n" for k, v in block.items())
    if _content(new) != [*before, block]:
        raise EditorError("could not add the hero block to manifest.toml cleanly; add it by hand")
    return new


def set_hero_abilities(text: str, block_id: str, steps: list[dict],
                       kind: str = "hero") -> str:
    """``text`` with hero block ``block_id``'s ``[[content.abilities]]`` steps
    replaced by ``steps``, everything else as it was. The steps are a sequence
    the build replays, so a save writes the whole list rather than adding to
    it: saving twice must not copy an ability twice. Refuses unless the result
    parses to exactly that change."""
    from .content import _toml
    lines = text.splitlines(keepends=True)
    heads = []                          # (line, header name, is an array table)
    for i, line in enumerate(lines):
        m = _HEADER_RE.match(line)
        if m:
            heads.append((i, m.group(1), line.strip().startswith("[[")))
    span = None
    for n, (i, name, arr) in enumerate(heads):
        if not (arr and name == "content"):
            continue
        end = next((j for j, nm, _a in heads[n + 1:] if not nm.startswith("content.")),
                   len(lines))
        try:
            got = tomllib.loads("".join(lines[i:end])).get("content", [{}])[0]
        except tomllib.TOMLDecodeError:
            continue
        if got.get("kind") == kind and got.get("id") == block_id:
            span = (n, i, end)
    if span is None:
        raise EditorError(f"no {kind} block {block_id!r} in manifest.toml")
    n, start, end = span
    while end > start and lines[end - 1].lstrip().startswith("#"):
        end -= 1                        # the next block's own comment
    drop: set[int] = set()
    inner = [(i, name) for i, name, _a in heads[n + 1:] if start < i < end]
    for k, (i, name) in enumerate(inner):
        if name == "content.abilities":
            stop = inner[k + 1][0] if k + 1 < len(inner) else end
            drop.update(range(i, stop))
    kept = [line for k, line in enumerate(lines[start:end], start) if k not in drop]
    body = "".join(kept).rstrip("\n") + "\n"
    for step in steps:
        body += "\n[[content.abilities]]\n" + "".join(
            f"{k} = {_toml(v)}\n" for k, v in step.items())
    new = "".join(lines[:start]) + body + ("\n" if end < len(lines) else "") + "".join(lines[end:])
    want = []
    for c in _content(text):
        if c.get("kind") == kind and c.get("id") == block_id:
            c = {k: v for k, v in c.items() if k != "abilities"}
            if steps:
                c["abilities"] = steps
        want.append(c)
    if _content(new) != want:
        raise EditorError("could not write the steps into that hero block cleanly (its "
                          "abilities may be written inline); edit manifest.toml by hand")
    return re.sub(r"\n{3,}", "\n\n", new)


# --- opening a mod ---------------------------------------------------------------

_ITEM_KEYS = {"kind", "id", "base", "mode", "name", "display_name", "description", "rarity",
              "icon", "value_patches", "stats", "super_description"}
_TALENT_KEYS = {"kind", "id", "hero", "file", "value_patches", "union_patches", "stats"}
#: The talent builder's block (``<prefix>_builder``, see ``content.talent_defs``).
_BUILDER_KEYS = {"kind", "id", "hero", "rebuild", "include", "add_stats", "scale"}
#: A card line the page did not write this session: it is never rewritten or
#: appended again, so text saved before (by the page or by hand) stays as it is.
_LOADED_LINE = "\u0000loaded"


def _tiers4(values, what: str) -> list[float]:
    """A builder entry's ``values`` as the page holds them: one per rarity."""
    if isinstance(values, (int, float)) and not isinstance(values, bool):
        return [float(values)] * 4
    if isinstance(values, list) and len(values) == 4:
        return [float(v) for v in values]
    if isinstance(values, dict):
        try:
            return [float(values[t]) for t in ("Common", "Rare", "Epic", "Legendary")]
        except (KeyError, TypeError, ValueError):
            pass
    raise EditorError(f"{what}: values the editor cannot show ({values!r})")


def _builder(f: dict, E: dict) -> None:
    """The builder block back into the page's state: rebuilt talents, included
    effects, added stats and bigger abilities."""
    if set(f) - _BUILDER_KEYS:
        raise EditorError("has fields the editor has no control for: "
                          + ", ".join(sorted(set(f) - _BUILDER_KEYS)))
    for t in f.get("rebuild") or []:
        E["rebuild"][str(t)] = True
    for e in f.get("include") or []:
        talent, other, hero = str(e.get("talent") or ""), str(e.get("from") or ""), e.get("hero")
        E["include"][talent] = f"{_hero_of(str(hero))}\u0000{other}" if hero else other
    for e in f.get("add_stats") or []:
        a = {"stat": str(e["stat"]), "values": _tiers4(e.get("values"), str(e["stat"])),
             "percent": bool(e.get("percent", True)), "line": _LOADED_LINE}
        for k in ("during", "after", "seconds", "cooldown", "next"):
            if e.get(k) is not None:
                a[k] = e[k]
        E["addStats"].setdefault(str(e["talent"]), []).append(a)
    for e in f.get("scale") or []:
        E["scale"].setdefault(str(e["talent"]), []).append({
            "node": str(e["node"]), "file": str(e.get("file") or ""),
            "values": _tiers4(e.get("values"), str(e["node"])),
            "percent": bool(e.get("percent", True)), "line": _LOADED_LINE})
_SKILL_KEYS = {"kind", "id", "hero", "source", "name", "description", "icon"}


def _data_url(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode("ascii")


def _suggest_id(base: str) -> str:
    """The page's ``suggestId``: as long as the base, and not the base."""
    tail = "_N" if base[-2:] == "_M" else "_M"
    return base[:-2] + tail if len(base) > 2 else base


def _item(mod_root: Path, f: dict) -> tuple[str, dict, dict]:
    """``(base, page state, payload)`` for an item block."""
    from . import content as C
    if set(f) - _ITEM_KEYS:
        raise EditorError("has fields the editor has no control for: "
                          + ", ".join(sorted(set(f) - _ITEM_KEYS)))
    mode = f.get("mode") or "clone"
    if mode not in ("clone", "replace"):
        raise EditorError(f"mode {mode!r} is not edited here")
    base = str(f.get("base") or "").replace("\\", "/").rpartition("/")[2]
    detail = C.item_detail(base)
    values = {r["label"]: r for r in detail["values"]}
    mods = {m["name"] for m in detail["modifiers"]}
    E = {"mode": mode, "id": f["id"] if mode == "clone" else _suggest_id(base),
         "name": str(f.get("name") or f.get("display_name") or ""),
         "description": str(f.get("description") or ""), "rarity": str(f.get("rarity") or ""),
         "icon": "", "iconUpload": "", "values": {}, "stats": {},
         "superDescription": str(f.get("super_description") or ""),
         "autoDesc": False, "autoSuper": False, "textMiss": []}
    for vp in f.get("value_patches") or []:
        label = vp.get("label") if isinstance(vp, dict) else vp[0]
        new = vp.get("new") if isinstance(vp, dict) else vp[2]
        if label not in values:
            raise EditorError(f"{base} has no value {label!r} any more")
        E["values"][label] = new
    for modifier, stat in (f.get("stats") or {}).items():
        if modifier not in mods:
            raise EditorError(f"{base} has no effect {modifier!r}")
        E["stats"][modifier] = str(stat)
    icon = str(f.get("icon") or "")
    if icon.startswith("icons/") and (mod_root / icon).is_file():
        E["iconUpload"] = _data_url(mod_root / icon)
    elif icon:
        stem = icon.replace("/", "\\").rpartition("\\")[2].removesuffix(".png")
        if not C._STEM_RE.match(stem):
            raise EditorError(f"icon {icon!r} is not one the editor offers")
        E["icon"] = stem
    payload = {"mode": mode, "base": base, "id": E["id"], "name": E["name"],
               "description": E["description"], "rarity": E["rarity"], "icon": E["icon"],
               "iconUpload": E["iconUpload"], "superDescription": E["superDescription"],
               "stats": [{"modifier": k, "stat": v} for k, v in E["stats"].items()],
               "values": [{"label": k, "old": values[k]["value"], "new": v,
                           "shadowed": values[k]["shadowed"]} for k, v in E["values"].items()]}
    return base, E, payload


def _hero_of(name: str) -> str:
    """The editor's hero (folder) name for a talent or skill block's ``hero``."""
    from . import content as C
    heroes = C.heroes()
    if name in heroes:
        return name
    back = {v: k for k, v in C._herodefs().items()}       # Sun_Wukong -> SunWukong
    if name in back:
        return back[name]
    raise EditorError(f"no hero {name!r}")


def _talent(f: dict, E: dict) -> None:
    from . import content as C
    if not f.get("file") and set(f) & (_BUILDER_KEYS - {"kind", "id", "hero"}):
        _builder(f, E)
        return
    if set(f) - _TALENT_KEYS:
        raise EditorError("has fields the editor has no control for: "
                          + ", ".join(sorted(set(f) - _TALENT_KEYS)))
    hero = _hero_of(str(f.get("hero") or ""))
    file = str(f.get("file") or "").removesuffix(".entity")
    rows = {(x["file"], v["label"]): v for x in C.talent_values(hero) for v in x["values"]}
    for vp in f.get("value_patches") or []:
        label, new = vp[0], vp[2]
        r = rows.get((file, label))
        if r is None:
            raise EditorError(f"{file} has no value {label!r} any more")
        E["values"][file + "\u0000" + label] = {"file": file, "label": label, "type": r["type"],
                                                "old": r["value"], "new": new,
                                                "shadowed": r["shadowed"]}
    for u in f.get("union_patches") or []:
        k = f"{file}\u0000{u['label']}\u0000{u['index']}"
        E["tiers"][k] = {"file": file, "label": u["label"], "index": u["index"],
                         "old": u["old"], "new": u["new"]}
    for modifier, stat in (f.get("stats") or {}).items():
        E["stats"][file + "\u0000" + modifier] = str(stat)


def _skill(mod_root: Path, f: dict, E: dict) -> None:
    if set(f) - _SKILL_KEYS:
        raise EditorError("has fields the editor has no control for: "
                          + ", ".join(sorted(set(f) - _SKILL_KEYS)))
    card = {k: str(f[k]) for k in ("name", "description") if f.get(k)}
    icon = str(f.get("icon") or "")
    if icon:
        if not (icon.startswith("icons/") and (mod_root / icon).is_file()):
            raise EditorError(f"icon {icon!r} is not a file in the mod")
        card["iconUpload"] = _data_url(mod_root / icon)
    card.setdefault("name", "")
    card.setdefault("description", "")
    E["cards"][str(f.get("source") or "")] = card


def load_mod(root: Path, mod_id: str) -> dict:
    """Everything the page needs to keep working on ``mods/<mod_id>``.

    ``items`` / ``talents``: ``{base or hero: {"edit": page state, "payload":
    what the page sends, "blocks": [[kind, id], ...]}}``; ``script``: the test
    grants or None; ``kept``: ``[{kind, id, why}]`` for every block left as
    it is."""
    from . import content as C
    if not C._MOD_ID_RE.match(mod_id):
        raise EditorError("a mod id takes letters, digits, - and _ only")
    mod_root = root / mod_id
    manifest = mod_root / "manifest.toml"
    if not manifest.is_file():
        raise EditorError(f"no mod {mod_id!r}")
    text = manifest.read_text(encoding="utf-8")
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise EditorError(f"manifest.toml does not parse: {e}") from e
    items: dict[str, dict] = {}
    talents: dict[str, dict] = {}
    kept: list[dict] = []
    for f in doc.get("content", []):
        if not isinstance(f, dict):
            continue
        kind, bid = f.get("kind"), str(f.get("id") or "")
        try:
            if kind == "item":
                base, E, payload = _item(mod_root, f)
                if base in items:
                    raise EditorError(f"a second block for {base}; the editor holds one per item")
                items[base] = {"edit": E, "payload": payload, "blocks": [[kind, bid]]}
            elif kind in ("talent", "skill"):
                hero = _hero_of(str(f.get("hero") or ""))
                entry = talents.setdefault(hero, {"edit": None, "blocks": [], "ids": []})
                if entry["edit"] is None:
                    entry["edit"] = {"prefix": "", "values": {}, "cards": {}, "tiers": {},
                                     "stats": {}, "addStats": {}, "rebuild": {}, "include": {},
                                     "scale": {}, "rarity": "Common", "q": ""}
                (_talent(f, entry["edit"]) if kind == "talent"
                 else _skill(mod_root, f, entry["edit"]))
                entry["blocks"].append([kind, bid])
                entry["ids"].append((kind, bid, f))
            else:
                kept.append({"kind": kind, "id": bid, "why": "not a kind the editor edits"})
        except EditorError as e:
            kept.append({"kind": kind, "id": bid, "why": str(e)})
    for hero, entry in list(talents.items()):
        entry["edit"]["prefix"] = _talent_prefix(hero, entry.pop("ids"))
        if entry["edit"]["prefix"] is None:
            for k, i in entry["blocks"]:
                kept.append({"kind": k, "id": i, "why": "its ids do not share one prefix"})
            del talents[hero]
            continue
        E = entry["edit"]
        entry["payload"] = {
            "hero": hero, "prefix": E["prefix"], "values": list(E["values"].values()),
            "tiers": list(E["tiers"].values()),
            "stats": [{"file": k.split("\u0000")[0], "modifier": k.split("\u0000")[1], "stat": v}
                      for k, v in E["stats"].items()],
            "cards": [{"source": s, **c} for s, c in E["cards"].items()],
            "addStats": [{"talent": t, **{k: v for k, v in a.items() if k != "line"}}
                         for t, rows in E["addStats"].items() for a in rows],
            "rebuild": list(E["rebuild"]),
            "include": [{"talent": t, "from": p.split("\u0000")[-1],
                         **({"hero": p.split("\u0000")[0]} if "\u0000" in p else {})}
                        for t, p in E["include"].items()],
            "scale": [{"talent": t, "node": r["node"], "file": r["file"], "values": r["values"],
                       "percent": r["percent"]} for t, rows in E["scale"].items() for r in rows]}
    script = program = None
    init = mod_root / "init.lua"
    if init.is_file():
        try:
            script = read_script(init.read_text(encoding="utf-8"))
        except EditorError as e:
            kept.append({"kind": "init.lua", "id": "test grants", "why": str(e)})
        try:
            program = read_blocks(init.read_text(encoding="utf-8"))
        except EditorError as e:
            kept.append({"kind": "init.lua", "id": "blocks", "why": str(e)})
    return {"id": mod_id, "name": str((doc.get("mod") or {}).get("name") or mod_id),
            "items": items, "talents": talents, "script": script, "program": program,
            "kept": kept}


def _talent_prefix(hero: str, blocks: list[tuple[str, str, dict]]) -> str | None:
    """The one block-id stem the page would have made all of ``blocks`` from
    (see ``content.talent_defs``), or None when they do not share one."""
    out = None
    for kind, bid, f in blocks:
        if kind == "talent" and not f.get("file") and bid.endswith("_builder"):
            prefix = bid[:-len("_builder")]
        elif kind == "talent":
            file = str(f.get("file") or "").removesuffix(".entity")
            slug = re.sub(r"[^A-Za-z0-9_]", "_", file.removeprefix(f"Hero_{hero}"))
            if slug and not bid.endswith(slug):
                return None
            prefix = bid[:-len(slug)] if slug else bid
        else:
            tail = "_" + re.sub(r"[^A-Za-z0-9_]", "_", str(f.get("source") or ""))
            if not bid.endswith(tail):
                return None
            prefix = bid[:-len(tail)]
        if out is not None and prefix != out:
            return None
        out = prefix
    return out or f"{hero.lower()}_talents"


# --- importing a mod (the web editor) --------------------------------------------

_IMPORT_RE = re.compile(r"^(?:manifest\.toml|init\.lua|icons/[A-Za-z0-9_]+\.png)$")


def import_mod(root: Path, files: dict) -> str:
    """Put an uploaded mod's editable files (``manifest.toml``, ``init.lua``,
    ``icons/*.png``) under ``root``. For the web editor, whose mods live only in
    the page; refuses to write over a mod that is already there."""
    from . import content as C
    if not isinstance(files, dict) or "manifest.toml" not in files:
        raise EditorError("that folder has no manifest.toml")
    blobs = {}
    for rel, b64 in files.items():
        if not isinstance(rel, str) or not _IMPORT_RE.match(rel):
            continue
        try:
            blobs[rel] = base64.b64decode(str(b64), validate=True)
        except ValueError:
            raise EditorError(f"{rel} did not arrive intact") from None
    try:
        doc = tomllib.loads(blobs["manifest.toml"].decode("utf-8"))
    except (UnicodeDecodeError, tomllib.TOMLDecodeError) as e:
        raise EditorError(f"manifest.toml does not parse: {e}") from e
    mod_id = str((doc.get("mod") or {}).get("id") or files.get("_folder") or "")
    if not C._MOD_ID_RE.match(mod_id):
        raise EditorError("the manifest has no usable [mod] id")
    target = root / mod_id
    if target.exists():
        raise EditorError(f"a mod named {mod_id!r} is already open here")
    for rel, data in blobs.items():
        dest = target / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
    (target / "assets").mkdir(exist_ok=True)
    return mod_id
