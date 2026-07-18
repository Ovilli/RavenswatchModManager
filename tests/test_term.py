"""Terminal styling tests.

The load-bearing property is the negative one: the desktop app shells out to
this CLI and parses its output, so ANSI codes must never reach a pipe.
"""

from __future__ import annotations

import io

import pytest

from rsmm.cli import _term


class FakeStream(io.StringIO):
    def __init__(self, tty: bool):
        super().__init__()
        self._tty = tty

    def isatty(self) -> bool:
        return self._tty


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for var in ("NO_COLOR", "FORCE_COLOR", "CLICOLOR_FORCE", "TERM"):
        monkeypatch.delenv(var, raising=False)


def test_disabled_when_not_a_tty():
    assert _term.color_enabled(FakeStream(tty=False)) is False


def test_enabled_on_a_tty():
    assert _term.color_enabled(FakeStream(tty=True)) is True


def test_no_color_beats_tty(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    assert _term.color_enabled(FakeStream(tty=True)) is False


def test_no_color_beats_force_color(monkeypatch):
    monkeypatch.setenv("NO_COLOR", "1")
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert _term.color_enabled(FakeStream(tty=True)) is False


def test_force_color_on_a_pipe(monkeypatch):
    monkeypatch.setenv("FORCE_COLOR", "1")
    assert _term.color_enabled(FakeStream(tty=False)) is True


def test_dumb_terminal_disables(monkeypatch):
    monkeypatch.setenv("TERM", "dumb")
    assert _term.color_enabled(FakeStream(tty=True)) is False


def test_stream_without_isatty_is_safe():
    assert _term.color_enabled(object()) is False


def test_plain_style_emits_no_escapes():
    s = _term.Style(enabled=False)
    for text in (s("x", "red"), s.bold("x"), s.ok("x"), s.err("x"), s.heading("x")):
        assert "\033" not in text
        assert text == "x"


def test_styled_wraps_and_resets():
    s = _term.Style(enabled=True)
    assert s("x", "red") == "\033[31mx\033[0m"
    assert s("x", "bold", "cyan") == "\033[1;36mx\033[0m"
    # unknown style names are ignored rather than raising
    assert s("x", "not_a_style") == "x"
    # no styles requested -> untouched
    assert s("x") == "x"


def test_rule_and_bar_are_plain_when_disabled():
    s = _term.Style(enabled=False)
    assert "\033" not in _term.rule("label", s)
    assert "\033" not in _term.bar(0.5, 10, s)
    assert _term.bar(0.5, 10, s) == "█" * 5 + "░" * 5


def test_bar_clamps_out_of_range():
    s = _term.Style(enabled=False)
    assert _term.bar(-5, 8, s) == "░" * 8
    assert _term.bar(99, 8, s) == "█" * 8


@pytest.mark.parametrize(
    ("n", "expected"),
    [(0, "0 B"), (512, "512 B"), (1024, "1.0 KB"), (1536, "1.5 KB"),
     (1048576, "1.0 MB"), (1073741824, "1.0 GB")],
)
def test_human_bytes(n, expected):
    assert _term.human_bytes(n) == expected


def test_width_is_clamped():
    assert 60 <= _term.width() <= 160
