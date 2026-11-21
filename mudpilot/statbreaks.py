"""Stat and mana-regen breakpoints (0.8.200, Dan). The game rounds every derived value down, so a stat only changes
something at certain values: Dodge = (AGI − 50) ÷ 3 goes up at 53, 56, 59… This shows, for each stat, what it feeds
and the next value where each of those goes up — and for casters, the ManaRgn% values where the mana tick goes up,
so a flux/ntap/nity reroll target can sit on a breakpoint instead of a round number.

Formulas are MajorMUD's (Stock and Paradigm differ in places), as worked out by the MudPlay project (MIT) from the
game's own code; "≈" marks the ones that game mixes with other values.
"""
from __future__ import annotations

MIN_STAT, MAX_STAT = 30, 250
STATS = ("Strength", "Intellect", "Willpower", "Agility", "Health", "Charm")


def mana_tick(level, intellect, willpower, charm, mtype, mlvl, regen_pct=0, para=True, meditating=False) -> int:
    """Mana a 30-second tick pays (meditating: before ManaRgn%). mtype: 1 mage (INT), 2 priest (WIL), 3 druid
    ((INT+WIL)/2), 4 bard (CHA), 5 kai."""
    if not mtype:
        return 0
    if mtype == 5:
        return (regen_pct + 100) // 100
    base = {1: intellect, 2: willpower, 3: (intellect + willpower) // 2, 4: charm}.get(mtype, 0)
    if not base:
        return 0
    regen = (level + 20) * base * (mlvl + 2) // 1650
    if meditating:
        return regen
    return regen + regen_pct * regen // 100 if para else (regen_pct + 100) * regen // 100


def regen_breakpoints(level, intellect, willpower, charm, mtype, mlvl, base_pct=0, lo=-100, hi=250, para=True):
    """[(extra ManaRgn% needed on top of base_pct, tick it gives)] — each step where the tick goes up."""
    out, prev = [], None
    for extra in range(lo, hi + 1):
        t = mana_tick(level, intellect, willpower, charm, mtype, mlvl, base_pct + extra, para)
        if prev is None or t != prev:
            out.append((extra, t))
        prev = t
    return out


def _fl(a, b):
    return a // b if a >= 0 else -((-a) // b)        # the game truncates toward zero


def columns(stat, level=1, para=True, mtype=0, mlvl=0, others=None, picks=False, thief=False, tracks=False):
    """[(label, formula, f(v) -> value, approx)] for one stat. others: {'Intellect': n, …} for a druid's mana."""
    o = others or {}
    lv = max(1, int(level or 1))
    cols = []

    def add(label, formula, f, approx=False):
        cols.append((label, formula, f, approx))

    if stat == "Agility":
        add("Dodge", "(AGI − 50) ÷ 3", lambda v: _fl(v - 50, 3))
        if para:
            add("Accuracy", "(AGI − 50) ÷ 3", lambda v: _fl(v - 50, 3))
        add("Bash accuracy" if para else "Accuracy", "(AGI − 50) ÷ 6", lambda v: _fl(v - 50, 6))
        add("Crit", "(AGI − 50) ÷ 20", lambda v: _fl(v - 50, 20))
        add("Stealth", "AGI ÷ 4", lambda v: v // 4, approx=para)
        if picks:
            add("Picklocks", "AGI ÷ 7" if para else "AGI × 2 ÷ 7", (lambda v: v // 7) if para else (lambda v: v * 2 // 7),
                approx=True)
        if thief:
            add("Thievery", "AGI ÷ 6", lambda v: v // 6, approx=True)
    elif stat == "Charm":
        add("Dodge", "(CHA − 50) ÷ 5", lambda v: _fl(v - 50, 5))
        if para:
            add("Accuracy", "(CHA − 50) ÷ 10", lambda v: _fl(v - 50, 10))
        add("Crit", "(CHA − 50) ÷ 30", lambda v: _fl(v - 50, 30))
        add("Stealth", "CHA ÷ 6", lambda v: v // 6, approx=para)
        add("Perception", "CHA ÷ 8", lambda v: v // 8, approx=True)
        if picks and para:
            add("Picklocks", "CHA × 2 ÷ 7", lambda v: v * 2 // 7, approx=True)
        if mtype == 4:
            add("Spellcasting", "CHA ÷ 2", lambda v: v // 2, approx=True)
            add("Mana / tick", f"({lv} + 20) × CHA × {mlvl + 2} ÷ 1650",
                lambda v: mana_tick(lv, 0, 0, v, 4, mlvl, 0, para))
        add("Buy price", "−(CHA ÷ 5 − 10) %", lambda v: -(v // 5 - 10))
        if para:
            add("Sell price", "half value ± (CHA − 50) ÷ 5 %", lambda v: _fl(v - 50, 5))
        else:
            add("Sell price", "(CHA ÷ 2 + 25) % of value", lambda v: v // 2 + 25)
    elif stat == "Intellect":
        if para:
            add("Accuracy", "(INT − 50) ÷ 6", lambda v: _fl(v - 50, 6))
        add("Crit", "(INT − 50) ÷ 10", lambda v: _fl(v - 50, 10))
        add("Stealth", "INT ÷ 8", lambda v: v // 8, approx=para)
        add("Magic res", "INT ÷ 4", lambda v: v // 4, approx=True)
        add("Perception", "INT × 5 ÷ 8", lambda v: v * 5 // 8, approx=True)
        if picks:
            add("Picklocks", "INT ÷ 7" if para else "INT × 2 ÷ 7", (lambda v: v // 7) if para else (lambda v: v * 2 // 7),
                approx=True)
        if tracks:
            add("Tracking", "INT ÷ 4", lambda v: v // 4, approx=True)
        sc = {1: ("INT ÷ 2", lambda v: v // 2), 2: ("INT ÷ 6", lambda v: v // 6), 3: ("INT ÷ 3", lambda v: v // 3)}
        if mtype in sc:
            add("Spellcasting", sc[mtype][0], sc[mtype][1], approx=True)
        if mtype == 1 and mlvl:
            add("Mana / tick", f"({lv} + 20) × INT × {mlvl + 2} ÷ 1650", lambda v: mana_tick(lv, v, 0, 0, 1, mlvl, 0, para))
        if mtype == 3 and mlvl:
            w = int(o.get("Willpower") or 0) or 0
            add("Mana / tick", f"({lv} + 20) × ((INT + WIL {w}) ÷ 2) × {mlvl + 2} ÷ 1650",
                lambda v: mana_tick(lv, v, w or v, 0, 3, mlvl, 0, para), approx=not w)
    elif stat == "Strength":
        if not para:
            add("Accuracy", "(STR − 50) ÷ 3", lambda v: _fl(v - 50, 3))
            add("Min damage", "2 × ((STR − 100) ÷ 10), not below 0", lambda v: max(0, _fl(v - 100, 10) * 2))
            add("Max damage", "(STR − 50) ÷ 10", lambda v: _fl(v - 50, 10))
        else:
            add("Min damage", "(STR − 100) ÷ 10, not below 0", lambda v: max(0, _fl(v - 100, 10)))
            add("Max damage", "(STR − 50) ÷ 10, not below 0", lambda v: max(0, _fl(v - 50, 10)))
            add("Bash accuracy", "(STR − 50) ÷ 3", lambda v: _fl(v - 50, 3))
        add("Carry weight", "STR × 48 (+ STR × 36 − 3600 above 100)",
            lambda v: v * 48 + (v * 36 - 3600 if v > 100 else 0))
    elif stat == "Health":
        d = 500 if para else 750
        add("HP / tick", f"({lv} + 20) × HEA ÷ {d}, at least 1", lambda v: max(1, (lv + 20) * v // d))
        add("Max HP (HEA's share)", f"HEA ÷ 2 + (HEA − 50) × {lv} ÷ 16", lambda v: v // 2 + _fl((v - 50) * lv, 16))
    elif stat == "Willpower":
        add("Magic res", "WIL × 3 ÷ 4", lambda v: v * 3 // 4, approx=True)
        add("Perception", "WIL ÷ 4", lambda v: v // 4, approx=True)
        if tracks:
            add("Tracking", "WIL ÷ 8", lambda v: v // 8, approx=True)
        sc = {1: ("WIL ÷ 6", lambda v: v // 6), 4: ("WIL ÷ 6", lambda v: v // 6), 2: ("WIL ÷ 2", lambda v: v // 2),
              3: ("WIL ÷ 3", lambda v: v // 3)}
        if mtype in sc:
            add("Spellcasting", sc[mtype][0], sc[mtype][1], approx=True)
        if mtype == 2 and mlvl:
            add("Mana / tick", f"({lv} + 20) × WIL × {mlvl + 2} ÷ 1650", lambda v: mana_tick(lv, 0, v, 0, 2, mlvl, 0, para))
        if mtype == 3 and mlvl:
            i = int(o.get("Intellect") or 0) or 0
            add("Mana / tick", f"({lv} + 20) × ((INT {i} + WIL) ÷ 2) × {mlvl + 2} ÷ 1650",
                lambda v: mana_tick(lv, i or v, v, 0, 3, mlvl, 0, para), approx=not i)
    return cols


def next_steps(f, now, count=2, hi=MAX_STAT):
    """[(stat value, new value)] for the next `count` values above `now` where f changes."""
    out, cur = [], f(now)
    for v in range(now + 1, hi + 1):
        y = f(v)
        if y != cur:
            out.append((v, y))
            cur = y
            if len(out) >= count:
                break
    return out


# ---------------------------------------------------------------- window (Window → Stat breakpoints)
def char_context(app):
    """(level, para, mtype, mlvl, stats{name: value}, class name) from what the game has told us."""
    st, s = app.s.state, app.s
    para = "paradigm" in (s.settings.board or "").lower() or "para" in (s.settings.board or "").lower()
    cls = next((c for c in (s.world.classes or {}).values()
                if (c.get("Name") or "").lower() == (st.char_class or "").lower()), {}) if st.char_class else {}
    stats = {"Strength": st.strength, "Intellect": st.intellect, "Willpower": st.willpower, "Agility": st.agility,
             "Health": st.health, "Charm": st.charm}
    return (st.level or s.settings.char_level or 1, para, int(cls.get("MageryType") or 0),
            int(cls.get("MageryLVL") or 0), stats, cls.get("Name") or st.char_class or "")


def make_pane(parent, app):
    import tkinter as tk
    from tkinter import ttk
    f = ttk.Frame(parent, padding=10)
    head = ttk.Label(f, text="", style="Head.TLabel")
    head.pack(anchor="w")
    note = ttk.Label(f, text="", style="Muted.TLabel", wraplength=820, justify="left")
    note.pack(anchor="w", pady=(2, 6))
    nb = ttk.Notebook(f)
    nb.pack(fill="both", expand=True)

    # stats
    sf = ttk.Frame(nb, padding=6)
    nb.add(sf, text="Stats")
    top = ttk.Frame(sf)
    top.pack(fill="x")
    ttk.Label(top, text="Stat").pack(side="left")
    which = tk.StringVar(value="Intellect")
    cb = ttk.Combobox(top, values=STATS, textvariable=which, state="readonly", width=12)
    cb.pack(side="left", padx=6)
    ttk.Label(top, text="value").pack(side="left", padx=(12, 0))
    val = tk.StringVar()
    ttk.Spinbox(top, from_=MIN_STAT, to=MAX_STAT, textvariable=val, width=6).pack(side="left", padx=6)
    cols_ = ("What it feeds", "Now", "Goes up at", "Then", "After that", "Formula")
    t = ttk.Treeview(sf, columns=cols_, show="headings", height=12)
    for c, w in zip(cols_, (150, 70, 90, 70, 110, 330)):
        t.heading(c, text=c)
        t.column(c, width=w, anchor="w")
    t.pack(fill="both", expand=True, pady=6)

    # mana regen
    mf = ttk.Frame(nb, padding=6)
    nb.add(mf, text="Mana regen")
    mtop = ttk.Label(mf, text="", wraplength=820, justify="left")
    mtop.pack(anchor="w")
    mcols = ("Spell roll needed (ManaRgn +)", "Mana a tick", "Per minute")
    mt = ttk.Treeview(mf, columns=mcols, show="headings", height=12)
    for c, w in zip(mcols, (220, 120, 120)):
        mt.heading(c, text=c)
        mt.column(c, width=w, anchor="w")
    mt.pack(fill="both", expand=True, pady=6)

    def fill(*_a):
        lv, para, mtype, mlvl, stats, cname = char_context(app)
        st = app.s.state
        head.configure(text=f"{cname or 'Character'} — level {lv} · {'Paradigm' if para else 'Stock'} formulas")
        known = all(stats.values())
        note.configure(text=("" if known else "Type 'stat' in the game so MudPilot has your stats (until then it uses "
                             "the value box). ") + "Each line is that stat's own share, rounded down the way the game "
                             "does; ≈ = mixed with other values in the game.")
        name = which.get()
        try:
            v = int(val.get())
        except ValueError:
            v = stats.get(name) or 50
        aid = lambda n: st.abil_value(n, "total")
        cols = columns(name, lv, para, mtype, mlvl, stats,
                       picks=bool(st.picklocks), thief=False, tracks=False)
        t.delete(*t.get_children())
        for label, formula, fn, approx in cols:
            nxt = next_steps(fn, v, 2)
            t.insert("", "end", values=(label + (" ≈" if approx else ""), fn(v),
                                        nxt[0][0] if nxt else "—", nxt[0][1] if nxt else "",
                                        f"{nxt[1][1]} at {nxt[1][0]}" if len(nxt) > 1 else "", formula))
        mt.delete(*mt.get_children())
        if not mtype:
            mtop.configure(text="This class has no mana.")
            return
        tot, sp = aid("145"), st.abil_value("145", "spells")
        base = (tot[0] if tot else 0) - (sp[0] if sp else 0)
        now = (tot[0] if tot else 0)
        tick_now = mana_tick(lv, stats["Intellect"], stats["Willpower"], stats["Charm"], mtype, mlvl, now, para)
        mtop.configure(text=f"ManaRgn now {now:+d} (gear, race and class {base:+d}, spell {now - base:+d}) → "
                            f"{tick_now} mana a tick. The tick only goes up at these spell rolls — set a flux / ntap / "
                            "nity reroll target on one of them; anything between buys nothing."
                            + ("" if tot else " (No 'abil 145' read yet: base taken as 0.)"))
        for extra, tick in regen_breakpoints(lv, stats["Intellect"], stats["Willpower"], stats["Charm"], mtype, mlvl,
                                             base, lo=-100, hi=200, para=para):
            if tick <= 0 and extra < 0:
                continue
            mt.insert("", "end", values=(f"{extra:+d}", tick, tick * 2))

    def pick(*_a):
        lv, para, mtype, mlvl, stats, cname = char_context(app)
        val.set(str(stats.get(which.get()) or 50))
        fill()
    cb.bind("<<ComboboxSelected>>", pick)
    val.trace_add("write", fill)
    pick()
    return f
