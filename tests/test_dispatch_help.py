"""The top-level help must list every command `main()` can route.

This exists because the listing used to be a hand-maintained docstring in
`./rsmm` and drifted badly: 23 of 44 routed commands had fallen out of it and
were undiscoverable from the CLI. `render_help()` derives the listing from the
routing table, and these tests fail if that link is ever broken.
"""

from __future__ import annotations

import importlib
import re

import pytest

from rsmm.cli import _dispatch as D

_ANSI = re.compile(r"\033\[[0-9;]*m")


def _plain_help() -> str:
    return _ANSI.sub("", D.render_help())


def _routed() -> set[str]:
    return {name for name, _mod in D.iter_commands()}


def test_every_routed_command_appears_in_the_help():
    text = _plain_help()
    missing = [c for c in sorted(_routed())
               if not re.search(rf"(?m)^\s+{re.escape(c)}(\s|$)", text)]
    assert not missing, f"routed but not listed in `rsmm --help`: {missing}"


def test_every_routed_command_is_grouped_not_dumped_in_other():
    """The `other` bucket is a safety net, not a destination — a command
    landing there means someone added a route without describing it."""
    documented = {c for _g, rows in D.COMMAND_GROUPS for c, _a, _d in rows}
    assert not (_routed() - documented), (
        "add these to _dispatch.COMMAND_GROUPS: "
        f"{sorted(_routed() - documented)}"
    )


def test_help_describes_nothing_that_cannot_be_run():
    """The reverse drift: a described command whose route was deleted would
    advertise a subcommand that errors out."""
    documented = {c for _g, rows in D.COMMAND_GROUPS for c, _a, _d in rows}
    assert not (documented - _routed()), (
        f"described in COMMAND_GROUPS but not routed: {sorted(documented - _routed())}"
    )


def test_every_description_is_present_and_terse():
    for _group, rows in D.COMMAND_GROUPS:
        for cmd, _args, desc in rows:
            assert desc, f"{cmd} has no description"
            assert len(desc) <= 60, f"{cmd} description too long for the column"


@pytest.mark.parametrize("cmd,module", sorted(set(D.iter_commands())))
def test_every_routed_module_imports_and_has_main(cmd, module):
    """A route pointing at a module with no `main()` fails only when the user
    runs it; `_dispatch_module` would print 'has no main()' and return 2."""
    mod = importlib.import_module(module)
    assert hasattr(mod, "main"), f"{cmd} -> {module} has no main()"


def test_help_is_plain_when_colour_is_disabled(monkeypatch):
    """`rsmm --help | less` and the desktop sidecar must not get escapes."""
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.delenv("FORCE_COLOR", raising=False)
    assert "\033" not in D.render_help()


def test_help_columns_align_because_padding_precedes_styling(monkeypatch):
    """Padding a styled string counts ANSI bytes as width. Guard against a
    regression by checking the coloured render collapses to the plain one."""
    monkeypatch.setenv("FORCE_COLOR", "1")
    monkeypatch.delenv("NO_COLOR", raising=False)
    coloured = D.render_help()
    assert "\033" in coloured
    monkeypatch.setenv("NO_COLOR", "1")
    assert _ANSI.sub("", coloured) == D.render_help()
