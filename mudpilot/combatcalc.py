"""Combat calculator: you vs a monster, both ways.

* your melee damage per round with a weapon (MME's CalculateAttack, via gearcalc)
* your attack spells against it, after its magic resistance and elemental resists
* how hard it hits you per round (MME's monster attack simulator, via monattack)
* rounds to kill it vs rounds until it kills you

Everything starts from what MudPilot already knows about your character (stat, level,
inventory) and can be changed by hand to try "what if" gear and stats.
"""
from __future__ import annotations

import re
import tkinter as tk
from tkinter import ttk

from . import gearcalc as G
from .spells import is_attack_spell, spell_kind

MUTED, GOOD, BAD, WARN = "#8a94a6", "#5cff7a", "#ff6b6b", "#e6b450"


def _tree(parent, cols, widths, height=6):
    t = ttk.Treeview(parent, columns=cols, show="headings", height=height)
    for c, w in zip(cols, widths):
        t.heading(c, text=c)
        t.column(c, width=w, anchor="w")
    return t


def quick(session, mon) -> dict:
    """You vs this monster in a few numbers, from what MudPilot knows about you (no window): your best damage a
    round (attack spells or melee with what you're wielding), its average damage a round to you (MME's attack
    simulator), rounds each way, HP lost per kill, and a one-word verdict. Best spots lists these per monster."""
    s = session
    st, cfg, w = s.state, s.settings, s.world
    lvl = st.level or cfg.char_level or 30
    hp_me = st.max_hp or 300
    out = {"name": mon.get("name"), "exp": int(mon.get("exp") or 0), "hp": int(mon.get("hp") or 0)}
    best = 0
    try:
        cands = list(s.spell_candidates())
        rows = s.spellbook.evaluate(cands, mon, lvl, s.bot.spellcasting(), cfg.spell_dmg_bonus) if cands else []
        best = max([eff for _sp, _r, eff, ratio, _c, _src in rows if ratio >= cfg.spell_min_pct / 100] or [0])
    except Exception:
        pass
    melee = 0
    try:
        from .gamestate import wielded
        name = wielded(getattr(st, "carrying", "") or "").lower()
        g = next((x for x in w.gear.values() if (x.get("name") or "").lower() == name), None) if name else None
        g = g or {"name": "fists", "abils": {}, "Speed": 1000, "Min": 1, "Max": 4, "StrReq": 0, "Accy": 0}
        cname = (st.char_class or cfg.char_class or "").lower()
        c = next((c for c in w.classes.values() if c.get("Name", "").lower() == cname), {})
        f = G.Fighter(level=lvl, combat=max(int(c.get("CombatLVL") or 3) - 2, 0), agility=st.agility or 50,
                      strength=st.strength or 50, encum_pct=int(st.enc[3]) if st.enc else 33)
        melee = G.weapon_round(g, f, mon, G.attack_kind(cfg.attack_cmd)).round_dmg
    except Exception:
        pass
    mine = max(best, melee)
    out["how"] = "spells" if best > melee else "melee"
    out["dmg"] = mine
    out["kill"] = max(1, -(-out["hp"] // mine)) if mine and out["hp"] else None
    avg = None
    try:
        from . import monattack
        user = {"ac": getattr(st, "ac", 0) or 0, "dr": getattr(st, "dr", 0) or 0, "dodge": 0,
                "mr": getattr(st, "magic_res", 0) or 50, "rfir": 0, "rcol": 0, "rlit": 0, "rsto": 0, "rwat": 0,
                "antimagic": False, "prot_evil": 0}
        sim = monattack.simulate(w, mon["num"], user, rounds=600, seed=1, greatermud=(cfg.exp_formula == "greatermud"))
        avg = sim["avg"] if sim else None
    except Exception:
        avg = None
    if avg is None:
        avg = float((mon.get("attack_data") or {}).get("mme_avg") or 0) or None
    out["hit"] = avg
    out["die"] = max(1, int(hp_me / avg)) if avg else None
    lose = (out["kill"] * avg) if (out["kill"] and avg) else None
    out["lose_pct"] = round(100 * lose / hp_me) if lose is not None else None
    if not mine:
        out["verdict"] = "can't hurt it"
    elif lose is None:
        out["verdict"] = "easy"
    elif lose >= hp_me:
        out["verdict"] = "deadly"
    elif lose >= hp_me * 0.4:
        out["verdict"] = "hurts"
    elif lose >= hp_me * 0.15:
        out["verdict"] = "fine"
    else:
        out["verdict"] = "easy"
    return out


class CombatCalc(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app, self.s = app, app.s
        st, cfg, w = self.s.state, self.s.settings, self.s.world
        self.v = {}
        left = ttk.Frame(self)
        left.pack(side="left", fill="y")
        right = ttk.Frame(self)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))

        # ---- monster picker
        mf = ttk.LabelFrame(left, text="Monster", padding=8)
        mf.pack(fill="x")
        self.q = tk.StringVar()
        e = ttk.Entry(mf, textvariable=self.q, width=26)
        e.pack(fill="x")
        self.q.trace_add("write", lambda *a: self._search())
        self.mlist = tk.Listbox(mf, height=8, background="#0f1318", foreground="#e0e6ef", borderwidth=0,
                                selectbackground="#1f7a4a", exportselection=False)
        self.mlist.pack(fill="x", pady=(4, 0))
        self.mlist.bind("<<ListboxSelect>>", lambda e: self.run())
        ttk.Button(mf, text="Monsters in this room", command=self._room_mobs).pack(fill="x", pady=(4, 0))
        self._mnums = []

        # ---- you
        yf = ttk.LabelFrame(left, text="You", padding=8)
        yf.pack(fill="x", pady=(8, 0))
        self.classes = [c.get("Name") for _k, c in sorted(w.classes.items())]
        self.v["class"] = tk.StringVar(value=st.char_class or cfg.char_class or (self.classes[0] if self.classes else ""))
        ttk.Label(yf, text="Class").grid(row=0, column=0, sticky="w")
        ttk.Combobox(yf, textvariable=self.v["class"], values=self.classes, width=12, state="readonly").grid(
            row=0, column=1, sticky="w", pady=1)
        hp_now = st.max_hp or 0
        fields = (("level", "Level", st.level or cfg.char_level or 30), ("hp", "Max HP", hp_now or 300),
                  ("strength", "Strength", st.strength or 60), ("agility", "Agility", st.agility or 60),
                  ("encum", "Encumbrance %", self._enc_pct()), ("accuracy", "Accuracy", 0), ("crit", "Crit %", 0),
                  ("ac", "Armour class", getattr(st, "ac", 0)), ("dr", "Damage resist", getattr(st, "dr", 0)),
                  ("dodge", "Dodge", 0), ("mr", "Magic resist", getattr(st, "magic_res", 0) or 50),
                  ("rfir", "Resist fire %", 0), ("rcol", "Resist cold %", 0), ("rlit", "Resist lightning %", 0),
                  ("rsto", "Resist stone %", 0), ("rwat", "Resist water %", 0))
        for i, (k, lbl, val) in enumerate(fields, start=1):
            self.v[k] = tk.StringVar(value=str(val))
            ttk.Label(yf, text=lbl).grid(row=i, column=0, sticky="w")
            ttk.Spinbox(yf, from_=-500, to=99999, width=8, textvariable=self.v[k]).grid(row=i, column=1, sticky="w", pady=1)
        n = len(fields) + 1
        ttk.Label(yf, text="Weapon").grid(row=n, column=0, sticky="w")
        self.weapons = sorted((g["name"], num) for num, g in (getattr(w, "gear", {}) or {}).items()
                              if int(g.get("ItemType") or -1) == 1 and g.get("name"))
        self.v["weapon"] = tk.StringVar(value=self._wielded() or "(fists)")
        ttk.Combobox(yf, textvariable=self.v["weapon"], values=["(fists)"] + [x[0] for x in self.weapons],
                     width=22).grid(row=n, column=1, sticky="w", pady=1)
        ttk.Button(yf, text="Calculate", style="Accent.TButton", command=self.run).grid(
            row=n + 1, column=0, columnspan=2, sticky="we", pady=(8, 0))
        ttk.Label(yf, text="Filled from 'stat' and your inventory; change anything to try other gear.",
                  style="Muted.TLabel", wraplength=240).grid(row=n + 2, column=0, columnspan=2, sticky="w", pady=(4, 0))
        for k, var in self.v.items():
            var.trace_add("write", lambda *a: self._later())

        # ---- results
        self.summary = ttk.Label(right, text="Pick a monster.", style="Head.TLabel", justify="left", wraplength=640)
        self.summary.pack(anchor="w")
        self.mon_info = ttk.Label(right, text="", style="Muted.TLabel", justify="left", wraplength=640)
        self.mon_info.pack(anchor="w", pady=(2, 6))
        a = ttk.LabelFrame(right, text="You → it", padding=6)
        a.pack(fill="x")
        self.melee_lbl = ttk.Label(a, text="", justify="left")
        self.melee_lbl.pack(anchor="w")
        self.sp_tree = _tree(a, ("Spell", "Kind", "Rated", "Vs it", "%", "Mana", "Dmg/mana"),
                             (150, 70, 60, 60, 50, 50, 70), height=7)
        self.sp_tree.tag_configure("bad", foreground=BAD)
        self.sp_tree.tag_configure("best", foreground=GOOD)
        self.sp_tree.pack(fill="x", pady=(4, 0))
        b = ttk.LabelFrame(right, text="It → you", padding=6)
        b.pack(fill="both", expand=True, pady=(8, 0))
        self.hit_lbl = ttk.Label(b, text="", justify="left")
        self.hit_lbl.pack(anchor="w")
        self.at_tree = _tree(b, ("Attack", "Type", "Used %", "Hits %", "Avg hit", "Resisted %"),
                             (170, 70, 60, 60, 60, 70), height=6)
        self.at_tree.pack(fill="both", expand=True, pady=(4, 0))
        self._after = None
        self._search()

    # ------------------------------------------------------------ inputs
    def _enc_pct(self):
        enc = self.s.state.enc
        return int(enc[3]) if enc else 33

    def _wielded(self):
        st = self.s.state
        from .gamestate import wielded
        name = wielded(getattr(st, "carrying", "") or "").lower()
        if not name:
            return None
        return next((n for n, _num in self.weapons if n.lower() == name), None)

    def _num(self, k, default=0):
        try:
            return int(float(self.v[k].get()))
        except (ValueError, tk.TclError):
            return default

    def _later(self):
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(500, self.run)

    def _search(self):
        q = self.q.get().strip().lower()
        self.mlist.delete(0, "end")
        self._mnums = []
        mons = self.s.world.monsters
        rows = sorted(((m["name"], num) for num, m in mons.items() if not q or q in m["name"].lower()),
                      key=lambda x: (not x[0].lower().startswith(q), x[0]))[:300]
        for name, num in rows:
            m = mons[num]
            self.mlist.insert("end", f"{name}  ({int(m.get('exp') or 0):,} exp)" + ("  ★" if m.get("boss") else ""))
            self._mnums.append(num)

    def _room_mobs(self):
        v = self.s.state.view
        recs = [rec for _s, rec in (v.monsters if v else []) if rec]
        if not recs:
            return
        self.q.set("")
        self.mlist.delete(0, "end")
        self._mnums = []
        for rec in recs:
            self.mlist.insert("end", rec["name"])
            self._mnums.append(rec["num"])
        self.mlist.selection_set(0)
        self.run()

    def show(self, num):
        """Open on this monster (Best spots: double-click one)."""
        mon = self.s.world.monsters.get(num)
        if not mon:
            return
        self.q.set(mon["name"])                     # the search fills the list…
        self._search()
        if num in self._mnums:
            i = self._mnums.index(num)
            self.mlist.selection_clear(0, "end")
            self.mlist.selection_set(i)
            self.mlist.see(i)
            self.run()

    def _mon(self):
        sel = self.mlist.curselection()
        if not sel:
            return None
        return self.s.world.monsters.get(self._mnums[sel[0]])

    # ------------------------------------------------------------ calc
    def fighter(self):
        w = self.s.world
        cname = self.v["class"].get().lower()
        c = next((c for c in w.classes.values() if c.get("Name", "").lower() == cname), {})
        return G.Fighter(level=self._num("level", 1), combat=max(int(c.get("CombatLVL") or 3) - 2, 0),
                         agility=self._num("agility", 50), strength=self._num("strength", 50),
                         encum_pct=self._num("encum", 33), accuracy=self._num("accuracy"), crit=self._num("crit"))

    def run(self):
        mon = self._mon()
        if not mon:
            return
        cfg, book = self.s.settings, self.s.spellbook
        lvl = self._num("level", 1)
        ab = mon.get("abils") or {}
        res = []
        for a, n in ((3, "cold"), (5, "fire"), (65, "stone"), (66, "lightning"), (147, "water")):
            val = ab.get(a, ab.get(str(a)))
            if val:
                res.append(f"r{n} {val}%")
        self.mon_info.configure(text=f"{mon['name']}: {mon.get('hp', '?')} HP · AC {mon.get('ac', 0)} / DR {mon.get('dr', 0)} · "
                                     f"MR {mon.get('mr', 0)} · {int(mon.get('exp') or 0):,} exp"
                                     + (f" · {', '.join(res)}" if res else "")
                                     + (" · undead" if mon.get("undead") else ""))
        # melee
        f = self.fighter()
        wname = self.v["weapon"].get().strip()
        num = next((n for nm, n in self.weapons if nm.lower() == wname.lower()), None)
        g = self.s.world.gear.get(num) if num is not None else None
        if g is None:
            g = {"name": "fists", "abils": {}, "Speed": 1000, "Min": 1, "Max": 4, "StrReq": 0, "Accy": 0}
        kinds = G.ATTACKS if g.get("name") != "fists" else ("normal",)
        swings = {k: G.weapon_round(g, f, mon, k) for k in kinds}
        pick = max(swings, key=lambda k: swings[k].round_dmg)
        sw = swings[pick]
        lines = []
        for k, x in swings.items():
            lines.append(f"{'▶ ' if k == pick else '   '}{k.capitalize():7} {x.round_dmg} dmg/round  "
                         f"({x.swings:.1f} swings, hit {x.hit_pct}%, crit {x.crit_pct}%, avg hit {x.avg_hit})")
        self.melee_lbl.configure(text=f"Melee with {g.get('name')}:\n" + "\n".join(lines)
                                      + (f"\n   — {sw.note}" if sw.note else ""))
        # spells
        self.sp_tree.delete(*self.sp_tree.get_children())
        cands = list(self.s.spell_candidates())
        rows = book.evaluate(cands, mon, lvl, self.s.bot.spellcasting(), cfg.spell_dmg_bonus) if cands else []
        best_spell = 0
        for i, (sp, rated, eff, ratio, c, src) in enumerate(rows):
            mana = int(sp.get("ManaCost") or 0)
            tag = "bad" if ratio < cfg.spell_min_pct / 100 else ("best" if i == 0 else "")
            if tag != "bad":
                best_spell = max(best_spell, eff)
            self.sp_tree.insert("", "end", tags=(tag,), values=(
                f"{sp.get('Short')} {sp.get('Name')}", spell_kind(sp) or "", rated, eff, f"{ratio:.0%}", mana,
                f"{eff / max(mana, 1):.1f}"))
        if not rows:
            self.sp_tree.insert("", "end", values=("(no attack spells known — 'spells' in game, or pick a caster class)",
                                                  "", "", "", "", "", ""))
        # it -> you
        self.at_tree.delete(*self.at_tree.get_children())
        sim = None
        try:
            from . import monattack
            user = {k: self._num(k) for k in ("ac", "dr", "dodge", "mr", "rfir", "rcol", "rlit", "rsto", "rwat")}
            user.update(antimagic=False, prot_evil=0)
            sim = monattack.simulate(self.s.world, mon["num"], user, rounds=3000, seed=1,
                                     greatermud=(cfg.exp_formula == "greatermud"))
        except Exception as ex:  # older MME import or sim not available
            self.hit_lbl.configure(text=f"Can't simulate its attacks: {ex}")
        if sim:
            self.hit_lbl.configure(text=f"About {sim['avg']:.0f} damage a round to you "
                                        f"(physical {sim.get('phys_avg', 0):.0f}, spells {sim.get('spell_avg', 0):.0f}); "
                                        f"worst round seen {sim.get('max_round_seen', 0)}, worst possible {sim.get('max_possible', 0)}")
            for at in sim.get("attacks", []):
                self.at_tree.insert("", "end", values=(at.get("name"), at.get("kind"), f"{at.get('used_pct', 0):.0f}",
                                                      f"{at.get('hit_pct', 0):.0f}", f"{at.get('avg_hit', 0):.0f}",
                                                      f"{at.get('resisted_pct', 0):.0f}"))
        elif sim is None and not self.hit_lbl.cget("text").startswith("Can't"):
            self.hit_lbl.configure(text="No attack data for this monster — re-import the board's MME file "
                                        "(File → Import MME database) to get it.")
        # summary
        mine = max(sw.round_dmg, best_spell)
        how = "spells" if best_spell > sw.round_dmg else (f"melee ({pick})" if pick != "normal" else "melee")
        hp = int(mon.get("hp") or 0)
        parts = []
        if mine > 0 and hp:
            parts.append(f"You kill it in about {max(1, -(-hp // mine))} round(s) with {how} ({mine}/round).")
        elif hp:
            parts.append("You can't hurt it with these numbers.")
        if sim and sim["avg"] > 0:
            yhp = self._num("hp", 1)
            die = max(1, int(yhp / sim["avg"]))
            parts.append(f"It would take about {die} round(s) to kill you from {yhp} HP.")
            if mine > 0 and hp:
                kill = max(1, -(-hp // mine))
                lose = kill * sim["avg"]
                parts.append(f"Expect to lose about {lose:.0f} HP ({100 * lose / max(yhp, 1):.0f}%) per kill.")
        self.summary.configure(text=" ".join(parts) or "—",
                               foreground=(BAD if sim and mine and hp and (-(-hp // mine)) * sim["avg"] >= self._num("hp", 1)
                                           else GOOD) if parts else MUTED)
