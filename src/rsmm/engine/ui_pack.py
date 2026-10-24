"""The in-game panel's look: the game's own UI art and fonts, decoded for the loader.

The loader draws its panel with Dear ImGui on the game's swapchain
(`src/loader/src/hook_overlay.cpp`). To look like the game it needs the game's
textures and bitmap fonts, but parsing cooked containers and decoding BC blocks
in C++ would duplicate `cooked` + `icon_decode` for no gain. So the CLI decodes
them here, on the player's machine and from the player's own install, into
``<game>/rsmm/ui/``:

    pack.json          what is there (sizes, font metrics and glyph tables)
    <key>.rgba         straight RGBA8 rows, width*height*4 bytes, no header

Nothing here is game data in the repo: it is regenerated from the install by
`rsmm install-loader` (``restore --all`` deletes ``<game>/rsmm/``). The loader
treats the pack as optional and falls back to ImGui's default look without it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .safeio import atomic_write_text

PACK_VERSION = 4
UI_DIR = "rsmm/ui"

#: key -> decoded texture path. The menu is drawn as the game's Settings
#: screen: the book's parchment pages, each under the Settings screen's own
#: ornament overlay (frame, vines, and on the left the title cartouche),
#: holding the option-menu kit.
TEXTURES: dict[str, str] = {
    "page_l": "Ui/BookMenu/UI_BookPageBg_L.png.Texture.dxt",
    "page_r": "Ui/BookMenu/UI_BookPageBg_R.png.Texture.dxt",
    "ornament_l": "Ui/BookMenu/Pages/UI_BookPageBg_Options1.png.Texture.dxt",
    "ornament_r": "Ui/BookMenu/Pages/UI_BookPageBg_Options2.png.Texture.dxt",
    "rule": "Ui/BookMenu/UI_Book_Deco_01.png.Texture.dxt",
    "deco": "Ui/OptionMenu/UI_Options_Deco.png.Texture.dxt",
    "button": "Ui/OptionMenu/UI_Options_MainButton.png.Texture.dxt",
    "button_hover": "Ui/OptionMenu/UI_Options_MainButton_Hover.png.Texture.dxt",
    "button_selected": "Ui/OptionMenu/UI_Options_MainButton_Selected.png.Texture.dxt",
    "button_disabled": "Ui/OptionMenu/UI_Options_MainButton_Disabled.png.Texture.dxt",
    "row": "Ui/OptionMenu/UI_Options_ParameterBg.png.Texture.dxt",
    "row_hover": "Ui/OptionMenu/UI_Options_ParameterBg_Hover.png.Texture.dxt",
    # The escape menu's own buttons (Resume / Settings / Abandon).
    "menu_button": "Ui/Common/UI_Button_Default_FixedSize_Normal.PNG.Texture.dxt",
    "menu_button_hover": "Ui/Common/UI_Button_Default_FixedSize_Selected.PNG.Texture.dxt",
    "confirm": "Ui/OptionMenu/UI_Options_ConfirmButton_Normal.png.Texture.dxt",
    "confirm_hover": "Ui/OptionMenu/UI_Options_ConfirmButton_Hover.png.Texture.dxt",
    "slider": "Ui/OptionMenu/UI_Options_SliderBg.png.Texture.dxt",
    "slider_handle": "Ui/OptionMenu/UI_Options_SliderHandle.png.Texture.dxt",
    "arrow": "Ui/OptionMenu/UI_Options_Arrow.png.Texture.dxt",
}

#: key -> decoded glyph-table path (`game_font.load` finds the page beside it).
FONTS: dict[str, str] = {
    "title": "Fonts/Germania One/Germania_One~GAM.fnt.Font.fnb",
    "body": "Fonts/Fontin Sans/Fontin_Sans_RG~GAM.fnt.Font.fnb",
}


#: Textures stored at a reduced size. The plain parchment is soft enough to
#: lose half its resolution; the ornament overlays are not (thin ink lines),
#: so they stay at 2048 and the loader's mipmaps do the shrinking.
MAX_EDGE: dict[str, int] = {"page_l": 1024, "page_r": 1024}


def _halve(rgba: bytes, width: int, height: int) -> tuple[bytes, int, int]:
    """Every other pixel of every other row. Point sampling, so fast in pure
    Python; fine for the soft parchment art it is used on."""
    from array import array

    w, h = width // 2, height // 2
    stride = width * 4
    out = array("I")
    for y in range(h):
        row = array("I", bytes(rgba[2 * y * stride:(2 * y + 1) * stride]))
        out.extend(row[::2][:w])
    return out.tobytes(), w, h


def _decode(rel: str) -> tuple[bytearray, int, int] | None:
    from . import cooked, corpus, icon_decode
    from .cooked_schemas.texture import TextureHandler

    raw = corpus.read(rel)
    if raw is None:
        return None
    try:
        tex = TextureHandler.parse_payload(cooked.parse(raw).sections[-1].payload)
        rgba = icon_decode.decode_to_rgba(tex.pixels, tex.width, tex.height, tex.format_name)
    except (ValueError, KeyError, IndexError):
        return None
    return rgba, tex.width, tex.height


def _exe_size(game_dir: Path) -> int | None:
    exe = game_dir / "Ravenswatch.exe"
    try:
        return exe.stat().st_size
    except OSError:
        return None


def current(game_dir: Path) -> bool:
    """Is the planted pack this version and from this game build?"""
    try:
        meta = json.loads((game_dir / UI_DIR / "pack.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return (meta.get("version") == PACK_VERSION
            and meta.get("game_exe_size") == _exe_size(game_dir))


def build(game_dir: Path) -> dict[str, Any]:
    """Decode every texture and font into ``<game>/rsmm/ui/``.

    Returns the manifest written. A piece the install lacks is left out and
    listed under ``missing``; the loader draws a plain stand-in for it.
    pack.json is written last, so an interrupted build reads as no pack.
    """
    from . import game_font

    out = game_dir / UI_DIR
    out.mkdir(parents=True, exist_ok=True)
    meta: dict[str, Any] = {"version": PACK_VERSION, "game_exe_size": _exe_size(game_dir),
                            "textures": {}, "fonts": {}, "missing": []}

    for key, rel in TEXTURES.items():
        got = _decode(rel)
        if got is None:
            meta["missing"].append(rel)
            continue
        rgba, w, h = got
        while max(w, h) > MAX_EDGE.get(key, 1 << 30) and min(w, h) >= 2:
            rgba, w, h = _halve(rgba, w, h)
        (out / f"{key}.rgba").write_bytes(bytes(rgba))
        meta["textures"][key] = {"file": f"{key}.rgba", "w": w, "h": h}

    for key, rel in FONTS.items():
        pair = game_font.load(rel)
        if pair is None:
            meta["missing"].append(rel)
            continue
        f, rgba, w, h = pair
        name = f"font_{key}.rgba"
        (out / name).write_bytes(bytes(rgba))
        meta["fonts"][key] = {
            "file": name, "w": w, "h": h,
            "size": f.size, "line_height": f.line_height, "base": f.base,
            # codepoint -> [x, y, w, h, xoff, yoff, xadvance], BMFont convention
            "glyphs": {str(cp): list(g) for cp, g in sorted(f.glyphs.items())},
        }

    atomic_write_text(out / "pack.json", json.dumps(meta, separators=(",", ":")))
    return meta
