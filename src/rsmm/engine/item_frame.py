"""An empty magical object, written from scratch: the frame an item with no
``base`` is built on.

A shipped item is a child of ``Objects\\Magical_Objects_Model`` that overrides a
few of the model's slots (68 of 69 shipped items, survey 2026-10-22): its name,
icon and quality values, its card text, its equipped state, plus a ``Dt
Magical Object Data`` part of its own that holds the item's save id. This writes
exactly those, with nothing else in the item: no stat, no listener, no super
effect (half the shipped items have none). The effects are added afterwards by
``item_effect``, so the whole item is written by rsmm and the only shipped file
it reads is the model it inherits from.

The frame goes through the same pipeline a copied base does
(``magic_item_cook.build_magic_item``), under the id ``FRAME_ID``, which renames
it, mints the item's own identity and save ids, and writes its text, icon and
quality.
"""

from __future__ import annotations

import struct

from . import cooked
from . import entity_parts as P
from .entity_graph_edit import EntityFile

#: The id the frame is written under; the build renames it to the item's.
FRAME_ID = "RSMM_Blank_Item"
MODEL = "Objects\\Magical_Objects_Model.entity.ot"
_MODEL_SCOPE = "Magical_Objects_Model"
_BANK = "Magical_Objects~GAM.xls"
#: A placeholder icon until the item sets its own (any vanilla icon works).
DEFAULT_ICON = "Objects\\Icon_Object_EternalRose.png"

#: The resource class and its bases, in a shipped item's class-table order.
_ROOT = ("oCEntitySettingsResource", "oIResource", "oISerializable", "oCEntitySettings",
         "oCSpawnableSettings", "oIEntityCpntSettings")


class FrameError(ValueError):
    pass


def _text(key: str) -> bytes:
    """A localized text value: ``Text`` + bank + row hint + key. The row hint
    is the key's row in the bank when the base wrote it; every copied item
    carries its base's stale one, so the game goes by the key."""
    return (struct.pack("<II", 0, 3) + P._lstr("Text") + P._lstr(_BANK)
            + struct.pack("<I", 0) + P._lstr(key))


def _resource(kind: str, path: str) -> bytes:
    return P._lstr(kind) + P._lstr(path)


def _empty_entity(parent: str, identity: bytes) -> bytes:
    """A cooked entity with no components that inherits ``parent``."""
    cf = cooked.CookedFile(variant="A", hdr_a=0x10, flags=1, extra=1, type_tag=0x31)
    for name in _ROOT:                  # the engine's entries, in table order
        c = next(x for x in P.class_source(name).classes if x.name == name)
        cf.classes.append(cooked.ClassDef(c.name, c.class_id, c.version_major,
                                          c.version_minor, c.parent_id))
    settings = [c.name for c in cf.classes].index("oCEntitySettings")
    trailer = (struct.pack("<I", 0) + cooked.MARK_BEGIN + struct.pack("<I", settings)
               + struct.pack("<I", 0)                       # component vector
               + b"\x00" + struct.pack("<I", 16) + identity
               + struct.pack("<I", 1) + P._lstr("EntitySettings") + P._lstr(parent)
               + b"\xff" * 4 + bytes(8) + cooked.MARK_END)
    cf.sections = [cooked.Section(struct.pack("<I", 0)), cooked.Section(trailer)]
    return cooked.emit(cf)


def build(read) -> bytes:
    """The frame entity, as a base with the id ``FRAME_ID``. ``read`` reads a
    shipped entity by reference (the model, for the slots it overrides)."""
    model_raw = read(MODEL)
    if model_raw is None:
        raise FrameError("the magical-object model is not readable (no install or mirror)")
    model = EntityFile(model_raw, _MODEL_SCOPE)
    w = P.PartWriter(EntityFile(_empty_entity(MODEL, _guid("identity")), FRAME_ID),
                     f"frame:{FRAME_ID}")

    def slot(name: str) -> P.Link:
        from .entity_graph_edit import kind_label
        c = model.component(name)
        path = c.path if c.group else c.name        # as shipped references name it
        return P.Link(c.guid, f"[{kind_label(c.cls)}] {_MODEL_SCOPE}\\{path}")

    def value(name: str, slot_name: str, num: P.Num) -> None:
        w.add("oCEntityCpntValueSettings", name, {"value": num, "flag": 0}, flags=0x101,
              override=slot(slot_name))

    lists = ("activates", "deactivates?", "list_2", "on_exit?", "disables_while_active?",
             "on_enter?", "while_active")
    w.add("oCEntityCpntStateSettings", "State Picked Up", dict.fromkeys(lists, []),
          flags=0x1, override=slot("Child State Equiped"))
    w.add("oCDtEntityCpntMagicalObjectDataSettings", "Dt Magical Object Data",
          flags=0x101, body=_item_data(w))
    text = P.Num(5, _text(f"{FRAME_ID}_Description"))
    w.add("oCEntityCpntStringFormatValueSettings", "Descripton Format",       # sic
          flags=0x101, override=slot("Descripton Format"),
          body=P.num_bytes(text, w.ci) + struct.pack("<I", 0))
    value("Icon Value", "Icon", P.Num(6, _resource("Ui", DEFAULT_ICON)))
    value("Name Value", "Name", P.Num(5, _text(f"{FRAME_ID}_Name")))
    value("Quality Value", "Quality", P.Num.int(0))
    return w.ef.to_bytes()


def _item_data(w: P.PartWriter) -> bytes:
    """The ``Dt Magical Object Data`` body after the common prefix: no tips, the
    save id, 1, 0, the countdown's full and current time (``items.md``: nothing
    counts down until an effect links them), and the v5 tail."""
    zero = P.num_bytes(P.Num.f32(0), w.ci)
    return (w.obj("TipsContainerSettings", struct.pack("<I", 0)) + _guid("save")
            + struct.pack("<I", 1) + b"\x00" + zero + zero + bytes(8))


def _guid(what: str) -> bytes:
    import uuid
    return uuid.uuid5(P._NS, f"frame:{FRAME_ID}:{what}").bytes
