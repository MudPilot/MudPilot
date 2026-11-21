"""Experience and CP tables, ported from MME (modMMudFunc.bas: CalcExpNeeded_STOCK /
CalcExpNeeded_GMUD, CalcCPLevel, frmMain.RefreshCPs).

exp_needed(level, chart) is the TOTAL experience needed to reach that level.
chart = class ExpTable + 100 + race ExpTable (MME's CalcExpNeededByRaceClass).
"""
from __future__ import annotations

MAX_UINT = 4294967295


def _fix(x: float) -> int:
    return int(x)          # VB Fix: truncate toward zero


def _mods_stock(n: int) -> tuple[int, int]:
    table = {3: (40, 20), 4: (44, 24), 5: (44, 24), 6: (48, 28), 7: (48, 28), 8: (52, 32), 9: (52, 32),
             10: (56, 36), 11: (56, 36), 12: (60, 40), 13: (60, 40), 14: (65, 45), 15: (65, 45),
             16: (70, 50), 17: (70, 50), 18: (75, 55)}
    if n in table:
        return table[n]
    return (50, 40) if n <= 26 else (23, 20)


def _stock_table(max_level: int, chart: int) -> list[int]:
    """Totals for levels 1..max_level (index 0 = level 1). Reproduces the game's
    32-bit rollover quirks exactly as MME does."""
    out = []
    run = 0
    billions = 0
    for i in range(1, max_level + 1):
        if i == 1:
            run = 0
        elif i == 2:
            run = chart * 10
        else:
            if i <= 27:
                mul, div = _mods_stock(i)
            elif i <= 55:
                mul, div = 115, 100
            elif i <= 58:
                mul, div = 109, 100
            else:
                mul, div = 108, 100
            pot = run * mul if mul and div else 0
            if pot > MAX_UINT:
                nd = 0
                while pot > MAX_UINT:
                    run = _fix(run / 100)
                    pot = run * mul
                    nd += 1
                alt = _fix((run * mul * 100) / div) if nd > 1 else _fix(pot / div)
                alt *= 100 ** nd
            else:
                alt = _fix(pot / div) if div else 0
            j = 1000000 * mul * billions
            while j > MAX_UINT:
                j -= MAX_UINT + 1
            while j >= 1000000000:
                j -= 1000000000
                billions += 1
            k = j + alt
            while k >= 1000000000:
                k -= 1000000000
                billions += 1
            run = k
        out.append(run + billions * 1000000000)
    return out


def _mods_gmud(n: int) -> tuple[int, int]:
    if n == 1:
        return 1, 1
    if n == 2:
        return 40, 20
    for lo, hi, v in ((3, 4, (44, 24)), (5, 6, (48, 28)), (7, 8, (52, 32)), (9, 10, (56, 36)), (11, 12, (60, 40)),
                      (13, 14, (65, 45)), (15, 16, (70, 50)), (17, 17, (75, 55)), (18, 25, (50, 40)),
                      (26, 32, (23, 20))):
        if lo <= n <= hi:
            return v
    return 0, 0


def _gmud(level: int, chart: int) -> int:
    res = _fix(chart * 1000 / 100)
    for i in range(max(level - 1, 0)):
        lvl = i + 1
        if i < 26:
            mul, div = _mods_gmud(i + 1)
        elif lvl < 34:
            mul, div = 115, 100
        else:
            mul, div = max(115 - (lvl - 34) // 5, 108), 100
        res = _fix(res * mul / div) if div else 0
    return res


def exp_needed(level: int, chart: int, greatermud: bool = False) -> int:
    if level <= 1:
        return 0
    if greatermud:
        return _gmud(level, chart)
    return _stock_table(level, chart)[-1]


def exp_table(world, cls_name: str, race_name: str, upto: int = 75, greatermud=False):
    """[(level, total exp, exp for that level)]"""
    chart = chart_for(world, cls_name, race_name)
    if chart is None:
        return []
    if greatermud:
        tot = [exp_needed(l, chart, True) for l in range(1, upto + 1)]
    else:
        tot = _stock_table(upto, chart)
    return [(l, tot[l - 1], tot[l - 1] - (tot[l - 2] if l > 1 else 0)) for l in range(1, upto + 1)]


def chart_for(world, cls_name, race_name):
    c = next((v for v in world.classes.values() if v.get("Name", "").lower() == (cls_name or "").lower()), None)
    r = next((v for v in world.races.values() if v.get("Name", "").lower() == (race_name or "").lower()), None)
    if not c or not r:
        return None
    return int(c.get("ExpTable", 0)) + 100 + int(r.get("ExpTable", 0))


def level_for_exp(exp: int, chart: int, greatermud=False) -> int:
    lvl = 1
    while lvl < 500 and exp_needed(lvl + 1, chart, greatermud) <= exp:
        lvl += 1
    return lvl


# ---------------------------------------------------------------- CP
def cp_for_level(level: int) -> int:
    """CP earned from levelling (on top of the race's BaseCP)."""
    return sum((i // 10) * 5 + 10 for i in range(1, max(level, 1)))


def stat_cost(points_above_min: int, greatermud=False) -> int:
    """CP to raise a stat this many points above the race minimum: 1 CP each for
    the first 10, 2 each for the next 10, ... (capped at 10 CP each on stock)."""
    cap = 9999 if greatermud else 10
    n = max(points_above_min, 0)
    cost, per = 0, 1
    while n > 0 and per < cap:
        take = min(n, 10)
        cost += take * per
        n -= take
        per += 1
    return cost + n * per


STATS = (("Strength", "STR"), ("Intellect", "INT"), ("Willpower", "WIL"), ("Agility", "AGL"),
         ("Health", "HEA"), ("Charm", "CHM"))


def cp_plan(world, race_name: str, stats: dict, level: int = 0, greatermud=False):
    """stats = {"STR": 60, ...}. Returns dict with per-stat cost, total, available and
    the level needed to afford it."""
    r = next((v for v in world.races.values() if v.get("Name", "").lower() == (race_name or "").lower()), None)
    if not r:
        return None
    per = {}
    for _n, k in STATS:
        want = int(stats.get(k, r.get("m" + k, 0)) or 0)
        lo, hi = int(r.get("m" + k, 0)), int(r.get("x" + k, 999))
        per[k] = {"min": lo, "max": hi, "want": want, "cost": stat_cost(want - lo, greatermud), "over": want > hi}
    total = sum(v["cost"] for v in per.values())
    base = int(r.get("BaseCP", 100))
    need_lvl = 1
    while base + cp_for_level(need_lvl) < total and need_lvl < 500:
        need_lvl += 1
    avail = base + cp_for_level(level) if level else None
    return {"stats": per, "total": total, "base": base, "level_needed": need_lvl,
            "available": avail, "left": (avail - total) if avail is not None else None}
