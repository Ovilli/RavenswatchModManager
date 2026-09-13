"""The `item-grid` config field: a mod-declared editor for lists of game items.

A mod describes the editor entirely in its own ``config_schema.toml`` — which
sections exist, which items each accepts, how many a section offers, an
optional number per item, and optionally a theme of game textures. The desktop
renders any such declaration with one generic component, and a content kind
reads the stored value. Neither the client nor the SDK knows what a particular
grid is for.

    [fields.shop]
    type   = "item-grid"
    label  = "Sandman shop"
    source = "shop-items"                   # allowlisted option provider
    title  = "The Sandman"                  # optional, the mod's own copy
    layout = "columns"                      # groups side by side (default "stack")
    quote  = "Every dream has its price."   # optional
    number = { attr = "price", label = "Price", min = 0, max = 99999, editable = "priceEditable" }

    [[fields.shop.sections]]
    id      = "minor"
    label   = "Offers"
    group   = "Minor dreams"          # sections sharing a group render together
    accepts = { role = "offer" }      # option attrs that must all match
    empty   = "Nothing chosen yet"     # optional, shown while it holds no items
    count   = { label = "Offers per visit", min = 1, max = 4, default = 4 }

    [fields.shop.theme]               # slot -> game texture, decoded from the install
    panel  = "Ui/SandMan/UI_SandManBg.png"
    header = { texture = "Ui/SandMan/UI_SandMan_categoriesBG.png", ink = "dark" }

A slot names its texture, and optionally the ``ink`` (``light`` or ``dark``)
that reads on it: the renderer cannot tell a parchment scroll from a slate
panel, so text colour on a themed element is the mod's call. Default ``light``.

Options come from the provider named in ``source`` (see
:mod:`rsmm.sdk.config_choices`), each with an ``attrs`` table. Two attribute
names carry meaning here: ``accepts`` filters on any of them, and a provider
may list the section ids an option sits in by default under ``defaultIn``.

The stored value keeps only what differs from those defaults::

    {sections = {minor = {items = [...], count = 2}}, numbers = {<item id> = 10}}

Theme textures are an allowlist too: a slot from :data:`THEME_SLOTS`, and a
``Ui/...png`` path the CLI resolves through the game's own asset map. Nothing
else is ever read, and nothing is shipped — the art is decoded from the
player's install when the editor opens.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .config import ConfigError

#: Theme slot -> longest edge the CLI decodes it at.
THEME_SLOTS: dict[str, int] = {
    "title": 1024,       # banner behind the title
    "panel": 512,        # frame around the sections (9-sliced)
    "header": 256,       # behind a section group's heading
    "separator": 512,    # between columns in the "columns" layout
    "details": 1024,     # behind the focused item's description
    "remove": 96,        # the remove button
    "removeHover": 96,
    "number": 64,        # behind an item's number
    "numberIcon": 64,    # icon beside the number
    "portrait": 512,     # image beside the title
    "quote": 256,        # behind the quote
}
_THEME_PATH = re.compile(r"^Ui/[A-Za-z0-9_ .\-/]+\.png$")
_ID = re.compile(r"^[A-Za-z0-9_\-]{1,64}$")
_MAX_SECTIONS = 32
_MAX_TEXT = 200
#: How section groups are arranged: one under another, or side by side.
LAYOUTS = ("stack", "columns")


@dataclass
class GridSection:
    id: str
    label: str
    group: str
    accepts: dict[str, Any]
    count: dict[str, Any] | None
    #: Shown while the section holds no items (e.g. "a random object").
    empty: str = ""


@dataclass
class GridNumber:
    attr: str
    label: str
    min: int
    max: int
    editable: str | None


@dataclass
class GridSpec:
    sections: list[GridSection] = field(default_factory=list)
    number: GridNumber | None = None
    theme: dict[str, str] = field(default_factory=dict)
    #: Theme slot -> "light" | "dark", the text colour that reads on it.
    ink: dict[str, str] = field(default_factory=dict)
    title: str = ""
    quote: str = ""
    layout: str = "stack"

    def as_dict(self) -> dict[str, Any]:
        return {
            "sections": [
                {"id": s.id, "label": s.label, "group": s.group, "accepts": s.accepts,
                 "count": s.count, "empty": s.empty}
                for s in self.sections
            ],
            "number": None if self.number is None else {
                "attr": self.number.attr, "label": self.number.label,
                "min": self.number.min, "max": self.number.max,
                "editable": self.number.editable,
            },
            "themeSlots": sorted(self.theme),
            "themeInk": {k: self.ink.get(k, "light") for k in sorted(self.theme)},
            "title": self.title,
            "quote": self.quote,
            "layout": self.layout,
        }


def _text(name: str, key: str, raw: Any) -> str:
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise ConfigError(f"{name}.{key}: expected text")
    return raw[:_MAX_TEXT]


def _int(name: str, key: str, raw: Any) -> int:
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ConfigError(f"{name}.{key}: expected a whole number")
    return raw


def parse(name: str, body: dict[str, Any]) -> GridSpec:
    """Validate an `item-grid` declaration from ``config_schema.toml``."""
    spec = GridSpec(title=_text(name, "title", body.get("title")),
                    quote=_text(name, "quote", body.get("quote")))
    layout = body.get("layout", "stack")
    if layout not in LAYOUTS:
        raise ConfigError(f"{name}.layout: one of {', '.join(LAYOUTS)}")
    spec.layout = layout

    sections = body.get("sections")
    if not isinstance(sections, list) or not sections:
        raise ConfigError(f"{name}: an item-grid needs at least one [[sections]] entry")
    if len(sections) > _MAX_SECTIONS:
        raise ConfigError(f"{name}: at most {_MAX_SECTIONS} sections")
    seen: set[str] = set()
    for i, sec in enumerate(sections):
        where = f"{name}.sections[{i}]"
        if not isinstance(sec, dict):
            raise ConfigError(f"{where}: expected a table")
        unknown = set(sec) - {"id", "label", "group", "accepts", "count", "empty"}
        if unknown:
            raise ConfigError(f"{where}: unknown key(s) {sorted(unknown)}")
        sid = sec.get("id")
        if not isinstance(sid, str) or not _ID.match(sid):
            raise ConfigError(f"{where}.id: expected letters, digits, _ or -")
        if sid in seen:
            raise ConfigError(f"{where}.id: {sid!r} is declared twice")
        seen.add(sid)
        accepts = sec.get("accepts") or {}
        if not isinstance(accepts, dict) or not all(
                isinstance(v, str | int | bool) and not isinstance(v, float)
                for v in accepts.values()):
            raise ConfigError(f"{where}.accepts: expected a table of attr = text/number/bool")
        count = sec.get("count")
        if count is not None:
            if not isinstance(count, dict) or set(count) - {"label", "min", "max", "default"}:
                raise ConfigError(f"{where}.count: expected {{label, min, max, default}}")
            lo = _int(where, "count.min", count.get("min", 1))
            hi = _int(where, "count.max", count.get("max", lo))
            default = _int(where, "count.default", count.get("default", hi))
            if not 1 <= lo <= default <= hi:
                raise ConfigError(f"{where}.count: need 1 <= min <= default <= max")
            count = {"label": _text(where, "count.label", count.get("label")),
                     "min": lo, "max": hi, "default": default}
        spec.sections.append(GridSection(
            id=sid, label=_text(where, "label", sec.get("label")) or sid,
            group=_text(where, "group", sec.get("group")), accepts=dict(accepts), count=count,
            empty=_text(where, "empty", sec.get("empty"))))

    number = body.get("number")
    if number is not None:
        if not isinstance(number, dict) or set(number) - {"attr", "label", "min", "max",
                                                          "editable"}:
            raise ConfigError(f"{name}.number: expected {{attr, label, min, max, editable}}")
        attr = number.get("attr")
        if not isinstance(attr, str) or not _ID.match(attr):
            raise ConfigError(f"{name}.number.attr: expected an attribute name")
        lo = _int(name, "number.min", number.get("min", 0))
        hi = _int(name, "number.max", number.get("max", 99999))
        if lo > hi:
            raise ConfigError(f"{name}.number: min is above max")
        editable = number.get("editable")
        if editable is not None and (not isinstance(editable, str) or not _ID.match(editable)):
            raise ConfigError(f"{name}.number.editable: expected an attribute name")
        spec.number = GridNumber(attr=attr, label=_text(name, "number.label", number.get("label")),
                                 min=lo, max=hi, editable=editable)

    theme = body.get("theme") or {}
    if not isinstance(theme, dict):
        raise ConfigError(f"{name}.theme: expected a table of slot = texture path")
    for slot, entry in theme.items():
        if slot not in THEME_SLOTS:
            raise ConfigError(
                f"{name}.theme.{slot}: unknown slot (one of {', '.join(sorted(THEME_SLOTS))})")
        ink = "light"
        if isinstance(entry, dict):
            if set(entry) - {"texture", "ink"}:
                raise ConfigError(f"{name}.theme.{slot}: expected {{texture, ink}}")
            ink = entry.get("ink", "light")
            if ink not in ("light", "dark"):
                raise ConfigError(f"{name}.theme.{slot}.ink: light or dark")
            entry = entry.get("texture")
        if not isinstance(entry, str) or not _THEME_PATH.match(entry) or ".." in entry:
            raise ConfigError(f"{name}.theme.{slot}: expected a game texture path like Ui/…/X.png")
        spec.theme[slot] = entry
        spec.ink[slot] = ink
    return spec


def coerce(name: str, spec: GridSpec, value: Any) -> dict[str, Any]:
    """Normalise a stored `item-grid` value against its declaration.

    Item ids are not checked against the provider: the options live in the
    install, and a config must survive being read where the game is not.
    """
    if value is None or value == "":
        return {}
    if not isinstance(value, dict) or set(value) - {"sections", "numbers"}:
        raise ConfigError(f"{name}: expected a table with `sections` and `numbers`")
    by_id = {s.id: s for s in spec.sections}
    out: dict[str, Any] = {}

    sections = value.get("sections") or {}
    if not isinstance(sections, dict):
        raise ConfigError(f"{name}.sections: expected a table")
    norm: dict[str, Any] = {}
    for sid in sorted(sections):
        sec = by_id.get(sid)
        if sec is None:
            raise ConfigError(f"{name}.sections: {sid!r} is not a declared section")
        entry = sections[sid]
        if not isinstance(entry, dict) or set(entry) - {"items", "count"}:
            raise ConfigError(f"{name}.sections.{sid}: expected {{items = [...], count = n}}")
        clean: dict[str, Any] = {}
        if "items" in entry:
            items = entry["items"]
            if not isinstance(items, list | tuple) or not all(isinstance(x, str) for x in items):
                raise ConfigError(f"{name}.sections.{sid}.items: expected a list of ids")
            clean["items"] = sorted({x.strip() for x in items if x.strip()})
            if not clean["items"]:
                raise ConfigError(f"{name}.sections.{sid}: a section needs at least one item")
        if "count" in entry:
            if sec.count is None:
                raise ConfigError(f"{name}.sections.{sid}: this section has no count")
            count = _int(name, f"sections.{sid}.count", entry["count"])
            if not sec.count["min"] <= count <= sec.count["max"]:
                raise ConfigError(
                    f"{name}.sections.{sid}.count: {sec.count['min']} to {sec.count['max']}")
            clean["count"] = count
        if clean:
            norm[sid] = clean
    if norm:
        out["sections"] = norm

    numbers = value.get("numbers") or {}
    if numbers:
        if spec.number is None:
            raise ConfigError(f"{name}.numbers: this grid declares no number")
        if not isinstance(numbers, dict):
            raise ConfigError(f"{name}.numbers: expected a table of item = number")
        nums: dict[str, int] = {}
        for item in sorted(numbers):
            n = numbers[item]
            if (isinstance(n, bool) or not isinstance(n, int | float) or n != int(n)
                    or not spec.number.min <= n <= spec.number.max):
                raise ConfigError(
                    f"{name}.numbers.{item}: a whole number from {spec.number.min} "
                    f"to {spec.number.max}")
            nums[str(item)] = int(n)
        out["numbers"] = nums
    return out
