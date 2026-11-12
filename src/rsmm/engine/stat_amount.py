"""What a stat bonus number MEANS, written so it cannot be misread.

A talent's ``add_stats`` value and an item effect's ``amount`` are ADDED to the
stat, in the stat's own unit: ``0.4`` on ``Attack power`` is +40%, ``0.25`` on
``CD reduce trait`` is 25% off the trait's cooldown, ``10`` on ``Armour`` is +10
armour. Bare decimals were read both ways by people and by AI helpers alike
("x0.4 per rarity" became +40% when -60% was meant), so a value may also be
written as text that says what it does:

* ``"+40%"`` / ``"-60%"``: a percentage, the same as ``0.4`` / ``-0.6``;
* ``"+10"`` / ``"-5"``: a plain amount, the same as ``10`` / ``-5``.

A multiplier (``"x0.4"``, ``"*0.4"``, ``"×0.4"``) is refused with the
equivalent to write instead: bonuses add up, they never scale the stat, so
"x0.4" can only mean "-60%", and only while nothing else changes that stat.

:func:`describe` is the read-back the build prints for every bonus, one line
per stat, so the author can check the numbers before playing.
"""

from __future__ import annotations

import math
import re

_PCT = re.compile(r"^([+-]?)\s*(\d+(?:\.\d+)?)\s*%$")
_NUM = re.compile(r"^([+-]?)\s*(\d+(?:\.\d+)?)$")
_MUL = re.compile(r"^[x×*]\s*(\d+(?:\.\d+)?)$|^(\d+(?:\.\d+)?)\s*[x×]$", re.IGNORECASE)


class AmountError(ValueError):
    pass


def parse(value, what: str = "value") -> float:
    """``value`` as the number added to the stat (see the module docstring)."""
    if isinstance(value, bool):
        raise AmountError(f"{what}: {value!r} is not a number")
    if isinstance(value, int | float):
        if not math.isfinite(value):
            raise AmountError(f"{what}: {value!r} is not a finite number")
        return float(value)
    if not isinstance(value, str):
        raise AmountError(f"{what}: {value!r} is not a number")
    text = value.strip()
    m = _PCT.match(text)
    if m:
        return (-1 if m[1] == "-" else 1) * float(m[2]) / 100.0
    m = _NUM.match(text)
    if m:
        return (-1 if m[1] == "-" else 1) * float(m[2])
    m = _MUL.match(text)
    if m:
        factor = float(m[1] or m[2])
        change = round((factor - 1.0) * 100.0, 4)
        return_as = f"{'+' if change >= 0 else ''}{change:g}%"
        raise AmountError(
            f"{what}: {value!r} is a multiplier, but stat bonuses ADD to the stat, they "
            f"do not scale it. Write {return_as!r} (the same as {change / 100:g}) for "
            f"what x{factor:g} means on its own")
    raise AmountError(f"{what}: {value!r} is not a number, a percentage like \"+40%\" / "
                      f"\"-60%\", or a plain amount like \"+10\"")


def fmt(amount: float, percent: bool) -> str:
    """``amount`` the way a card shows it: ``+40%`` or ``+10``."""
    if percent:
        v = round(amount * 100.0, 4)
        return f"{'+' if v >= 0 else ''}{v:g}%"
    return f"{'+' if amount >= 0 else ''}{amount:g}"


def describe(stat: str, amounts: dict[str, float], percent: bool) -> str:
    """One line saying what a bonus does at each rarity, e.g. ``Attack power:
    +40% / +43% / +46% / +50% (Common..Legendary), added to the hero's Attack
    power``. A ``reduce``/``decrease`` stat says which way a positive number
    goes, the usual way to get a cooldown backwards."""
    vals = list(amounts.values())
    shown = (fmt(vals[0], percent) + " at every rarity" if len(set(vals)) == 1
             else " / ".join(fmt(v, percent) for v in vals) + f" ({', '.join(amounts)})")
    line = f"{stat}: {shown}, added to the hero's {stat}"
    low = stat.lower()
    if "reduce" in low or "decrease" in low:
        line += " (a positive number means LESS: +25% here is 25% off)"
    elif any(v < 0 for v in vals):
        line += " (negative: a penalty)"
    return line
