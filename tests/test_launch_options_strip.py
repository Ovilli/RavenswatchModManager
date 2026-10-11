"""`restore --all` removes only the mod manager's launch options.

It used to write "" unconditionally, which also wiped the player's own
settings — on 2026-10-11 that removed a PRIME-offload set and the game went
straight back to "DX12 Error 0x80004005" on a hybrid-GPU laptop.
"""

import pytest

from rsmm.cli.run import add_rsmm_launch_options as add
from rsmm.cli.run import strip_rsmm_launch_options as strip

PRIME = ("__NV_PRIME_RENDER_OFFLOAD=1 __VK_LAYER_NV_optimus=NVIDIA_only "
         "__GLX_VENDOR_LIBRARY_NAME=nvidia")


@pytest.mark.parametrize(("before", "after"), [
    # the player's variables survive, ours go
    (f'{PRIME} WINEDLLOVERRIDES="winhttp=n,b" %command%', f"{PRIME} %command%"),
    # nothing but ours left -> Steam's default (empty)
    ('WINEDLLOVERRIDES="winhttp=n,b" %command%', ""),
    ("WINEDLLOVERRIDES=winhttp=native,builtin %command%", ""),
    # another DLL override in the same variable is the player's
    ('WINEDLLOVERRIDES="winhttp=n,b;dxgi=n" %command%', 'WINEDLLOVERRIDES="dxgi=n" %command%'),
    # loader-flag variables are ours; wrappers and game arguments are not
    ("RSMM_ENABLE_HERO_CAPTURE=1 gamemoderun %command% -dx11", "gamemoderun %command% -dx11"),
    ("gamemoderun %command%", "gamemoderun %command%"),
    ("", ""),
])
def test_strip_keeps_everything_but_ours(before, after):
    assert strip(before) == after


def test_strip_is_idempotent():
    once = strip(f'{PRIME} WINEDLLOVERRIDES="winhttp=n,b" %command%')
    assert strip(once) == once


# `rsmm run --set-launch-options/--force` ADDS the override; it used to replace
# any value without it by the bare recommended string, dropping the same PRIME
# variables a second way.


@pytest.mark.parametrize(("before", "after"), [
    ("", 'WINEDLLOVERRIDES="winhttp=n,b" %command%'),
    (f"{PRIME} %command%", f'WINEDLLOVERRIDES="winhttp=n,b" {PRIME} %command%'),
    # an assignment after a wrapper would be run as a command: front it
    ("gamemoderun %command%", 'WINEDLLOVERRIDES="winhttp=n,b" gamemoderun %command%'),
    ('WINEDLLOVERRIDES="dxgi=n" %command% -x',
     'WINEDLLOVERRIDES="dxgi=n;winhttp=n,b" %command% -x'),
    # no %command%: Steam treats the value as game arguments
    ("-novid", 'WINEDLLOVERRIDES="winhttp=n,b" %command% -novid'),
    # already there: untouched
    (f'{PRIME} WINEDLLOVERRIDES="winhttp=n,b" %command%',
     f'{PRIME} WINEDLLOVERRIDES="winhttp=n,b" %command%'),
])
def test_add_keeps_everything_and_adds_ours(before, after):
    assert add(before) == after


@pytest.mark.parametrize("value", [f"{PRIME} %command%", "gamemoderun %command% -x", ""])
def test_strip_undoes_add(value):
    assert strip(add(value)) == value
