"""Bounded tree observation without a running game or Windows process APIs."""
import importlib.util
from pathlib import Path

spec = importlib.util.spec_from_file_location(
    "nameplate_probe", Path(__file__).resolve().parents[1] / "tools/inspect_native_nameplate.py"
)
probe = importlib.util.module_from_spec(spec)
spec.loader.exec_module(probe)


def fixture():
    root, child = 0x100000, 0x200000
    memory = {}
    def put(address, value, size=8):
        data = value.to_bytes(size, "little")
        memory.update({address + i: b for i, b in enumerate(data)})
    for p, parent, name in ((root, 0, b"Top_Bar_Text_Frame"), (child, root, b"RSMM_Host_Crown")):
        put(p + 0x298, parent)
        put(p + 0x280, p + 0x1000)
        put(p + 0x288, len(name), 4)
        memory.update({p + 0x1000 + i: b for i, b in enumerate(name)})
        put(p + 0x234, 0x30, 1)
        put(p + 0x2d0, 16, 4); put(p + 0x2d4, 13, 4)
        put(p + 0x2a8, 0xffffffffffffffff)
        put(p + 8, 0xffffffffffffffff)
    put(root + 0x2a8, child)
    def read(p, size):
        try:
            return bytes(memory[p + i] for i in range(size))
        except KeyError:
            return None
    def info(p):
        if p not in (root, child):
            return None
        return {"ptr": hex(p), "class": ".?AVoCUI" + ("LayoutWindow" if p == root else "Picture") + "@@"}
    return root, child, put, read, info


def test_linked_tree_and_names():
    root, child, put, read, info = fixture()
    tree = probe.widget_tree(root, read, info)
    assert tree["complete"]
    assert [w["name"] for w in tree["widgets"]] == ["Top_Bar_Text_Frame", "RSMM_Host_Crown"]
    assert tree["widgets"][1]["size"] == [16, 13]


def test_cycle_is_bounded_and_not_success():
    root, child, put, read, info = fixture()
    put(child + 8, child)
    tree = probe.widget_tree(root, read, info)
    assert not tree["complete"]
    assert "invalid or cyclic child list" in tree["issues"]


def test_parent_mismatch_refuses_child():
    root, child, put, read, info = fixture()
    put(child + 0x298, 0x123400)
    tree = probe.widget_tree(root, read, info)
    assert not tree["complete"] and len(tree["widgets"]) == 1


def test_budget_is_not_reported_as_complete():
    root, child, put, read, info = fixture()
    tree = probe.widget_tree(root, read, info, max_nodes=1)
    assert not tree["complete"] and len(tree["widgets"]) == 1


def test_truncated_string_does_not_read_unbounded_memory():
    root, child, put, read, info = fixture()
    put(child + 0x288, 0x7fffffff, 4)
    tree = probe.widget_tree(root, read, info)
    assert tree["widgets"][1]["name"] is None
