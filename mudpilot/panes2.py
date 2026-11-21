"""More windows from pMUD: Combat summary, Item history (with stashed coins), Quest guide."""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk

from .windows import BG, PANEL, TEXT, MUTED, ACCENT, GRID, AMBER


def _tree(parent, cols, widths, height=10):
    f = ttk.Frame(parent)
    t = ttk.Treeview(f, columns=cols, show="headings", height=height)
    for c, w in zip(cols, widths):
        t.heading(c, text=c)
        t.column(c, width=w, anchor="w", stretch=c == cols[0])
    sb = ttk.Scrollbar(f, orient="vertical", command=t.yview)
    t.configure(yscrollcommand=sb.set)
    t.pack(side="left", fill="both", expand=True)
    sb.pack(side="right", fill="y")
    return f, t


def _pct(a, b):
    return f"{100 * a / b:.0f}%" if b else "—"


def _avg(total, n):
    return f"{total / n:.0f}" if n else "—"


class CombatSummaryPane(ttk.Frame):
    """Window → Combat summary: is the nuke landing, how much are we taking, per monster and per spell."""
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app, self.s = app, app.s
        top = ttk.Frame(self)
        top.pack(fill="x")
        self.head = ttk.Label(top, text="", style="Muted.TLabel")
        self.head.pack(side="left")
        ttk.Button(top, text="Reset", command=self._reset).pack(side="right")
        ttk.Label(self, text="Your attacks, by monster").pack(anchor="w", pady=(8, 2))
        f1, self.mt = _tree(self, ("Monster", "Kills", "Hit %", "Hits", "Miss", "Crit", "BS", "Avg hit", "Min–max",
                                   "Per round", "Spell dmg"),
                            (170, 50, 55, 50, 50, 45, 40, 65, 80, 75, 75), height=8)
        f1.pack(fill="both", expand=True)
        ttk.Label(self, text="What they did to you").pack(anchor="w", pady=(8, 2))
        f2, self.tt = _tree(self, ("Monster", "Hits", "Misses", "Avoided %", "Avg dmg", "Max", "Total"),
                            (170, 60, 60, 80, 70, 60, 70), height=6)
        f2.pack(fill="both", expand=True)
        row = ttk.Frame(self)
        row.pack(fill="both", expand=True, pady=(8, 0))
        left = ttk.Frame(row)
        left.pack(side="left", fill="both", expand=True)
        ttk.Label(left, text="Spells").pack(anchor="w", pady=(0, 2))
        f3, self.st = _tree(left, ("Spell", "Casts", "Hits", "Hit %", "Avg", "Min–max"),
                            (160, 50, 50, 55, 55, 80), height=6)
        f3.pack(fill="both", expand=True)
        right = ttk.Frame(row)
        right.pack(side="left", fill="both", expand=True, padx=(10, 0))
        ttk.Label(right, text="Last 10 rounds").pack(anchor="w", pady=(0, 2))
        f4, self.rt = _tree(right, ("When", "Monster", "Done", "Taken", "HP"), (70, 130, 55, 55, 90), height=6)
        f4.pack(fill="both", expand=True)
        self.refresh()

    def _reset(self):
        self.s.combatlog.reset()
        self.refresh(once=True)

    def refresh(self, once=False):
        if not self.winfo_exists():
            return
        cl = self.s.combatlog
        mins = max(1, (time.time() - cl.reset_t) / 60)
        self.head.configure(text=f"This session (since {time.strftime('%H:%M', time.localtime(cl.reset_t))}, "
                                 f"{mins:.0f} min)")
        for t in (self.mt, self.tt, self.st, self.rt):
            t.delete(*t.get_children())
        for name, m in sorted(cl.mobs.items(), key=lambda kv: -(kv[1]["dmg"] + kv[1]["spell_dmg"])):
            swings = m["hits"] + m["misses"]
            if swings or m["spell_hits"] or m["kills"]:
                self.mt.insert("", "end", values=(
                    name, m["kills"], _pct(m["hits"], swings), m["hits"], m["misses"], m["crits"], m["bs"],
                    _avg(m["dmg"], m["hits"]), f"{m['min'] or 0}–{m['max']}" if m["hits"] else "—",
                    _avg(m["round_dmg"], m["rounds"]), m["spell_dmg"] or ""))
            att = m["taken_hits"] + m["taken_miss"]
            if att:
                self.tt.insert("", "end", values=(name, m["taken_hits"], m["taken_miss"],
                                                  _pct(m["taken_miss"], att), _avg(m["taken"], m["taken_hits"]),
                                                  m["taken_max"], m["taken"]))
        for name, d in sorted(cl.spells.items(), key=lambda kv: -kv[1]["dmg"]):
            if d["casts"] or d["hits"]:
                casts = max(d["casts"], d["hits"])
                self.st.insert("", "end", values=(name, casts, d["hits"], _pct(d["hits"], casts),
                                                  _avg(d["dmg"], d["hits"]),
                                                  f"{d['min'] or 0}–{d['max']}" if d["hits"] else "—"))
        for r in reversed(list(cl.rounds)):
            self.rt.insert("", "end", values=(time.strftime("%H:%M:%S", time.localtime(r["t"])), r.get("mon") or "",
                                              r["done"], r["taken"], f"{r['hp0']}→{r['hp1']}"))
        if not once:
            self.after(2000, self.refresh)


class ItemHistoryPane(ttk.Frame):
    """Window → Item history: every item picked up, dropped, sold, given or stashed — when and where."""
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app, self.s = app, app.s
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Find").pack(side="left")
        self.q = tk.StringVar()
        ttk.Entry(top, textvariable=self.q, width=24).pack(side="left", padx=4)
        self.q.trace_add("write", lambda *a: self.refresh(once=True))
        ttk.Button(top, text="Copy", command=self.copy).pack(side="right")
        f, self.t = _tree(self, ("When", "What", "Qty", "Item", "Room", "Note"), (70, 80, 45, 220, 220, 120), height=16)
        f.pack(fill="both", expand=True, pady=6)
        self.wealth = ttk.Label(self, text="", style="Muted.TLabel", wraplength=700, justify="left")
        self.wealth.pack(anchor="w")
        self.refresh()

    def _rows(self):
        w, q = self.s.world, self.q.get().strip().lower()
        for t, what, n, it, room, note in reversed(list(self.s.combatlog.items)):
            rn = ""
            if room:
                r = w.room(room)
                rn = f"{room[0]}/{room[1]} {r.name if r else ''}"
            row = (time.strftime("%H:%M:%S", time.localtime(t)), what, n, it, rn, note)
            if q and q not in " ".join(str(x) for x in row).lower():
                continue
            yield row

    def copy(self):
        txt = "\n".join("\t".join(str(x) for x in r) for r in self._rows())
        self.clipboard_clear()
        self.clipboard_append(txt)

    def refresh(self, once=False):
        if not self.winfo_exists():
            return
        self.t.delete(*self.t.get_children())
        for r in self._rows():
            self.t.insert("", "end", values=r)
        from .gamestate import COIN_VALUE
        st = self.s.state
        stash = self.s.combatlog.stashed()
        left = sum(COIN_VALUE[k] * v for k, v in stash.items())
        carried = getattr(st, "wealth", 0) or 0
        parts = [f"{v:,} {k}{'s' if v != 1 else ''}" for k, v in stash.items() if v]
        self.wealth.configure(text=(f"Coins dropped or stashed this session: {', '.join(parts)} "
                                    f"(= {left:,} copper). " if parts else "No coins stashed this session. ")
                              + (f"Carried: {carried:,} copper · total with the stash: {carried + left:,} copper."
                                 if carried else ""))
        if not once:
            self.after(3000, self.refresh)


# ----------------------------------------------------------------- quest guide
def quest_guide(world, state, cfg, ab) -> list:
    """The steps of one quest flag, in order: [{from, to, how, where, needs, level, state}].
    state: done / now / level N / later."""
    from . import gearcalc as G
    steps = (getattr(world, "quest_steps", {}) or {}).get(int(ab)) or []
    cur = state.abil_rows.get(("granted", int(ab))) or state.abil_rows.get(("total", int(ab)))
    have = cur[0] if cur else (cfg.known_abils or {}).get(str(ab))
    have = int(have) if have is not None else None
    lvl = state.level or cfg.char_level or 0
    my_cls = (world.char or {}).get("class") if getattr(world, "char", None) else None
    out, seen = [], set()
    for s_ in steps:
        if s_["add"]:
            continue
        q = s_["req"]
        if q.get("classes") and my_cls is not None and my_cls not in q["classes"]:
            continue
        frm = 0
        for a, v in (q.get("abil_eq") or []) + (q.get("abil") or []):
            if int(a) == int(ab):
                frm = int(v)
        key = (frm, s_["value"], s_["how"], tuple(s_["where"][:1]))
        if key in seen:
            continue
        seen.add(key)
        needs = []
        for it in q.get("items") or []:
            g = (getattr(world, "gear", None) or {}).get(it) or {}
            src = [x[0] for x in (G.sources(world, g, limit=2) if g else []) if x[0] != "source unknown"]
            needs.append(world.item_name(it) + (f" ({'; '.join(src)})" if src else ""))
        for a, v in q.get("abil") or []:
            if int(a) != int(ab):
                needs.append(f"{state.abil_names.get(int(a)) or 'ability ' + str(a)} {v}+")
        if q.get("price"):
            needs.append(f"{q['price']:,} copper")
        if have is not None and have >= s_["value"]:
            st_ = "done"
        elif q.get("level") and lvl and lvl < q["level"]:
            st_ = f"level {q['level']}"
        elif have is not None and frm <= have < s_["value"]:
            st_ = "now"
        else:
            st_ = "later"
        out.append({"from": frm, "to": s_["value"], "how": s_["how"], "where": s_["where"][:1], "needs": needs,
                    "level": q.get("level") or 0, "state": st_})
    out.sort(key=lambda x: (x["to"], x["from"]))
    return out


class QuestGuidePane(ttk.Frame):
    """Window → Quest guide (pMUD): every quest flag MME knows, step by step — done, now, needs level N, later —
    with where each step happens (click to walk there) and what it needs (and where that comes from)."""
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app, self.s = app, app.s
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Button(top, text="Read my quest flags (abil)", command=self._read).pack(side="left")
        self.hide_done = tk.BooleanVar(value=True)
        ttk.Checkbutton(top, text="Hide finished quests", variable=self.hide_done, command=self.fill).pack(side="left", padx=10)
        body = ttk.Frame(self)
        body.pack(fill="both", expand=True, pady=6)
        lf, self.qt = _tree(body, ("Quest", "Yours", "Steps", "Next step"), (170, 50, 60, 300), height=20)
        lf.pack(side="left", fill="y")
        self.txt = tk.Text(body, background="#0f1318", foreground=TEXT, borderwidth=0, wrap="word",
                           font=("Segoe UI", 10), width=70)
        self.txt.pack(side="left", fill="both", expand=True, padx=(8, 0))
        for tag, col in (("done", "#5cff7a"), ("now", "#ffd166"), ("level", "#ff9a3c"), ("later", MUTED),
                         ("head", "#e8c470"), ("link", "#6cb8ff")):
            self.txt.tag_configure(tag, foreground=col)
        self.txt.tag_configure("link", underline=True)
        self.txt.tag_bind("link", "<Enter>", lambda e: self.txt.configure(cursor="hand2"))
        self.txt.tag_bind("link", "<Leave>", lambda e: self.txt.configure(cursor=""))
        self.qt.bind("<<TreeviewSelect>>", lambda e: self.show())
        ttk.Label(self, text="Steps for your class only. Yellow = your next step, orange = needs a higher level. "
                             "Click a room to walk there.", style="Muted.TLabel").pack(anchor="w")
        self.fill()

    def _read(self):
        if self.s.telnet.connected:
            self.s.send("abil", from_bot=True)
            self.after(4000, self.fill)

    def _qname(self, ab):
        return self.s.state.abil_names.get(int(ab)) or f"quest flag {ab}"

    def fill(self):
        sel = self.qt.selection()
        self.qt.delete(*self.qt.get_children())
        w, st, cfg = self.s.world, self.s.state, self.s.settings
        try:
            self.s.route_char()
        except Exception:
            pass
        for ab in sorted(getattr(w, "quest_steps", {}) or {}):
            g = quest_guide(w, st, cfg, ab)
            if not g:
                continue
            done = sum(1 for x in g if x["state"] == "done")
            if self.hide_done.get() and done == len(g):
                continue
            cur = st.abil_rows.get(("granted", ab)) or st.abil_rows.get(("total", ab))
            yours = cur[0] if cur else (cfg.known_abils or {}).get(str(ab), "?")
            # the next step at a glance (0.8.208, Dan: GoodQuest 16 — the dark phoenix is 17's, 16 is 'success')
            nx = next((x for x in g if x["state"] == "now"), None) or \
                next((x for x in g if x["state"].startswith("level")), None)
            if nx:
                r = w.room(tuple(nx["where"][0])) if nx["where"] else None
                nxt = (f"{nx['how']}" + (f" — {r.name}" if r else "") +
                       ("" if nx["state"] == "now" else f" ({nx['state']})"))
            else:
                nxt = "all done" if done == len(g) else ""
            self.qt.insert("", "end", iid=str(ab), values=(self._qname(ab), yours, f"{done}/{len(g)}", nxt))
        if sel and self.qt.exists(sel[0]):
            self.qt.selection_set(sel)
        elif self.qt.get_children():
            self.qt.selection_set(self.qt.get_children()[0])
        self.show()

    def show(self):
        self.txt.delete("1.0", "end")
        sel = self.qt.selection()
        if not sel:
            self.txt.insert("end", "No quest steps found in MME for your class.")
            return
        ab = int(sel[0])
        w = self.s.world
        self.txt.insert("end", f"{self._qname(ab)}\n\n", ("head",))
        for i, x in enumerate(quest_guide(w, self.s.state, self.s.settings, ab), 1):
            tag = "level" if x["state"].startswith("level") else x["state"]
            label = {"done": "✓ done", "now": "► next", "later": "later"}.get(x["state"], f"needs {x['state']}")
            self.txt.insert("end", f"{i}. [{label}] {x['from']} → {x['to']}: {x['how']}", (tag,))
            if x["where"]:
                rk = tuple(x["where"][0])
                r = w.room(rk)
                self.txt.insert("end", "  at ")
                lt = f"go{i}"
                self.txt.insert("end", f"{r.name if r else ''} ({rk[0]}/{rk[1]})", ("link", lt))
                self.txt.tag_bind(lt, "<Button-1>", lambda e, k=rk: self.app.goto_room(k))
            if x["needs"]:
                self.txt.insert("end", "\n     needs: " + ", ".join(x["needs"]), ("later",))
            self.txt.insert("end", "\n")
