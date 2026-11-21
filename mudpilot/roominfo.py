"""The pop-out map's side panel and record bar.

RoomPanel: click a room on the map → its name, number, area and exits, and every monster MME says can turn up there
(its own lair list, the area's monster groups, a boss's set room) with exp and HP — the ones standing there now marked
when it's your room. Click a monster for its MME sheet (MonsterInfo).

RecordBar: Record Path / Record Loop — walk it for real and it's written down (routerec.py)."""
from __future__ import annotations

import time
import tkinter as tk
from tkinter import ttk, messagebox, simpledialog

from .worlddb import DIR_WORDS

BG, PANEL, TEXT, MUTED = "#0f1318", "#161b22", "#e0e6ef", "#8a94a6"


def _area(world, key) -> str:
    r = world.room(key)
    return (r.name.split(",")[0].strip() if r else "") or "?"


# ---------------------------------------------------------------- monster sheet
def monster_lines(session, mon) -> list:
    """MME's sheet for a monster, as (heading, text) lines."""
    from .gearcalc import ABIL_NAMES
    w = session.world
    out = [("", mon["name"])]
    out.append(("Exp", f"{int(mon.get('exp') or 0):,}"))
    out.append(("HP", f"{mon.get('hp', '?')}"))
    out.append(("AC / DR", f"{mon.get('ac', 0)} / {mon.get('dr', 0)}"))
    out.append(("Magic resist", f"{mon.get('mr', 0)}"))
    ad = mon.get("attack_data") or {}
    spells = ad.get("spells") or {}
    for a in ad.get("att") or []:
        if not a.get("type") or (a.get("name") or "None") == "None":
            continue
        kind = {1: "melee", 2: "spell", 3: "rob"}.get(a.get("type"), f"type {a.get('type')}")
        txt = f"{a['name']} — {a.get('min', 0)}-{a.get('max', 0)} dmg, {float(a.get('true_pct') or 0):.0f}% of swings, " \
              f"accuracy {a.get('acc', 0)} ({kind})"
        hs = spells.get(str(a.get("hit_spell") or 0)) if a.get("hit_spell") else None
        if hs:
            txt += f"; on a hit: {hs.get('Name', '?')} ({hs.get('MinBase', 0)}-{hs.get('MaxBase', 0)})"
        out.append(("Attack", txt))
    for m in ad.get("mid") or []:
        if not m.get("spell"):
            continue
        sp = spells.get(str(m["spell"])) or w.spells.get(m["spell"]) or {}
        out.append(("Casts", f"{sp.get('Name', 'spell ' + str(m['spell']))} — {m.get('pct', 0)}% a round"
                             f"{', level ' + str(m['lvl']) if m.get('lvl') else ''}"))
    if ad.get("mme_avg"):
        out.append(("Damage a round", f"~{ad['mme_avg']:.0f} on average (MME's attack sim, no armour)"))
    flags = []
    if mon.get("undead"):
        flags.append("undead")
    for k, v in (mon.get("abils") or {}).items():
        nm = ABIL_NAMES.get(int(k), f"ability {k}")
        if nm in ("None",):
            continue
        flags.append(nm if not v else f"{nm} {v}")
    if mon.get("boss"):
        flags.append("boss")
    out.append(("Flags", ", ".join(flags) or "—"))
    if mon.get("regen_h"):
        out.append(("Respawn", f"{mon['regen_h']:g} h (set spawn)"))
    if mon.get("limit"):
        out.append(("Realm limit", f"{mon['limit']} at once"))
    try:
        drops = session.combatlog.mme_drops(mon)
    except Exception:
        drops = []
    out.append(("Drops", ", ".join(f"{n} {p:g}%" for n, p in drops[:14]) or "nothing listed in MME"))
    try:
        kills, seen = session.combatlog.seen_drops(mon["name"])
        if kills:
            out.append(("Your kills", f"{kills} counted" + (f"; seen: " + ", ".join(f"{n} ×{c[0]}" for n, c in list(
                seen.items())[:8]) if seen else "")))
    except Exception:
        pass
    try:
        from .combatcalc import quick
        q = quick(session, mon)
        if q.get("dmg"):
            out.append(("You vs it", f"~{q['dmg']:.0f} a round by {q['how']}"
                                     + (f", ~{q['kill']} rounds to kill" if q.get('kill') else "")))
    except Exception:
        pass
    return out


class MonsterInfo(tk.Toplevel):
    def __init__(self, app, mon):
        super().__init__(app.root)
        self.title(f"{mon['name']} — MudPilot")
        self.configure(background=PANEL)
        self.geometry("560x460")
        fr = ttk.Frame(self, padding=10)
        fr.pack(fill="both", expand=True)
        t = tk.Text(fr, background=BG, foreground=TEXT, borderwidth=0, wrap="word", padx=8, pady=6,
                    font=("Segoe UI", 10))
        t.tag_configure("h", foreground=MUTED)
        t.tag_configure("title", font=("Segoe UI", 13, "bold"))
        for k, v in monster_lines(app.s, mon):
            if not k:
                t.insert("end", v + "\n\n", "title")
            else:
                t.insert("end", f"{k}:  ", "h")
                t.insert("end", v + "\n")
        t.configure(state="disabled")
        t.pack(fill="both", expand=True)
        bf = ttk.Frame(fr)
        bf.pack(fill="x", pady=(8, 0))
        if hasattr(app, "open_combatcalc"):
            ttk.Button(bf, text="Combat calculator…", command=lambda: app.open_combatcalc(mon["num"])).pack(side="left")
        ttk.Button(bf, text="Close", command=self.destroy).pack(side="right")


# ---------------------------------------------------------------- room panel
class RoomPanel(ttk.Frame):
    def __init__(self, master, app, mapview):
        super().__init__(master, padding=(8, 4))
        self.app, self.s, self.m = app, app.s, mapview
        self.room = None
        self.head = ttk.Label(self, text="Click a room on the map", style="Head.TLabel", wraplength=260, justify="left")
        self.head.pack(anchor="w")
        self.sub = ttk.Label(self, text="", style="Muted.TLabel", wraplength=260, justify="left")
        self.sub.pack(anchor="w", pady=(2, 6))
        cols = ("name", "how", "exp", "hp", "here")
        self.t = ttk.Treeview(self, columns=cols, show="headings", height=12)
        for c, txt, wd in (("name", "Monster", 120), ("how", "How", 70), ("exp", "Exp", 60), ("hp", "HP", 40),
                           ("here", "Now", 34)):
            self.t.heading(c, text=txt)
            self.t.column(c, width=wd, anchor="w")
        self.t.pack(fill="both", expand=True)
        self.t.bind("<ButtonRelease-1>", lambda e: self.after(50, self._mon))
        self.t.bind("<Return>", self._mon)
        self._mons = {}
        self._last_open = None
        ttk.Label(self, text="Click a monster for its MME sheet", style="Muted.TLabel").pack(anchor="w", pady=(4, 0))
        bf = ttk.Frame(self)
        bf.pack(fill="x", pady=(6, 0))
        ttk.Button(bf, text="Go to", command=self._go).pack(side="left")
        ttk.Button(bf, text="Centre map", command=self._centre).pack(side="left", padx=6)
        self._tick()

    def show(self, room):
        self.room = tuple(room)
        self._fill()

    def _fill(self):
        w, st = self.s.world, self.s.state
        r = w.room(self.room) if self.room else None
        if not r:
            return
        k = self.room
        self.head.configure(text=f"{r.name}\n{k[0]}/{k[1]}")
        exits = ", ".join(DIR_WORDS.get(d, d).lower() + (" (door)" if ex.door else "") +
                          (" (hidden)" if not ex.visible else "") for d, ex in r.exits.items())
        extra = []
        if r.shop:
            extra.append("shop")
        if r.lair:
            extra.append("regen room")
        self.sub.configure(text=f"Area: {_area(w, k)}" + (f"  ·  {', '.join(extra)}" if extra else "") +
                                f"\nExits: {exits or 'none'}")
        here = k == st.room
        now = [sh.lower() for sh, _r in (st.view.monsters if here and st.view else [])]
        nowrec = [(_r or {}).get("name", "").lower() for _sh, _r in (st.view.monsters if here and st.view else [])]
        self.t.delete(*self.t.get_children())
        self._mons = {}
        rows = w.room_spawns(k)
        listed = set()
        for mon, how in sorted(rows, key=lambda x: (x[1] != "lair", -float(x[0].get("exp") or 0))):
            n_here = sum(1 for x in nowrec if x == mon["name"].lower())
            iid = self.t.insert("", "end", values=(mon["name"], how, f"{int(mon.get('exp') or 0):,}", mon.get("hp", ""),
                                                   f"×{n_here}" if n_here else ""))
            self._mons[iid] = mon
            listed.add(mon["name"].lower())
        for (sh, rec), nm in zip(st.view.monsters if here and st.view else [], nowrec):
            if nm and nm in listed:
                continue
            listed.add(nm or sh.lower())
            iid = self.t.insert("", "end", values=(sh, "here now", f"{int((rec or {}).get('exp') or 0):,}",
                                                   (rec or {}).get("hp", ""), "✓"))
            if rec:
                self._mons[iid] = rec
        if not rows and not now:
            self.t.insert("", "end", values=("(nothing spawns here in MME)", "", "", "", ""))
        self._sig = (k, tuple(now))

    def _tick(self):
        # your own room: keep "Now" current as monsters come and go
        try:
            st = self.s.state
            if self.room and self.room == st.room:
                now = tuple(sh.lower() for sh, _r in (st.view.monsters if st.view else []))
                if getattr(self, "_sig", None) != (self.room, now):
                    self._fill()
            self.after(1000, self._tick)
        except tk.TclError:
            pass

    def _mon(self, e=None):
        sel = self.t.selection()
        mon = self._mons.get(sel[0]) if sel else None
        if not mon:
            return
        lo = self._last_open
        if lo and lo[0] == mon["num"] and lo[1].winfo_exists():
            lo[1].lift()                          # (a double-click doesn't open it twice)
            return
        self._last_open = (mon["num"], MonsterInfo(self.app, mon))

    def _go(self):
        if self.room:
            self.app.goto_room(self.room)

    def _centre(self):
        if self.room:
            st = self.s.state
            self.m.scout = (self.room, st.room)
            self.m.redraw()


# ---------------------------------------------------------------- record bar
class RecordBar:
    def __init__(self, bar, app, mapview):
        self.app, self.s, self.m = app, app.s, mapview
        self.rr = self.s.routerec
        self.f = ttk.Frame(bar)
        self.f.pack(side="left", padx=(6, 0))
        self.b_path = ttk.Button(self.f, text="● Record Path", command=lambda: self._start("path"))
        self.b_loop = ttk.Button(self.f, text="● Record Loop", command=lambda: self._start("loop"))
        self.lbl = tk.Label(self.f, text="", foreground="#ff4d4d", background=PANEL, font=("Segoe UI", 9, "bold"))
        self.b_undo = ttk.Button(self.f, text="↶ Undo step", command=self._undo)
        self.b_save = ttk.Button(self.f, text="■ Stop / Save", style="Accent.TButton", command=self._save)
        self.b_cancel = ttk.Button(self.f, text="✕", width=3, command=self._cancel)
        # 0.8.187 (Dan, 2026-11-12: "I want a 3 room loop, i should be able to manually run around the map while it
        # makes a path"): ticked, you walk it for real (number pad / typing moves your character) and each room you
        # reach is a step; unticked, the number pad draws on this map and nothing goes to the game
        self.walk = tk.BooleanVar(value=False)
        self.c_walk = ttk.Checkbutton(self.f, text="walk it in the game", variable=self.walk)
        self._state = None
        app._record_bar = self
        self._tick()
        # draw mode: the number pad walks the pen (this window only; nothing goes to the game)
        self.f.winfo_toplevel().bind("<KeyPress>", self._key, add="+")

    def _layout(self):
        on = self.rr.active
        if on == self._state:
            return
        self._state = on
        for w in (self.b_path, self.b_loop, self.c_walk, self.lbl, self.b_undo, self.b_save, self.b_cancel):
            w.pack_forget()
        if on:
            for w in (self.lbl, self.b_undo, self.b_save, self.b_cancel):
                w.pack(side="left", padx=2)
        else:
            self.b_path.pack(side="left", padx=2)
            self.b_loop.pack(side="left", padx=2)
            self.c_walk.pack(side="left", padx=(4, 2))

    def _tick(self):
        try:
            self._layout()
            if self.rr.active:
                self.lbl.configure(text=self.rr.label())
                if int(time.time() * 2) % 2:
                    self.lbl.configure(text="●" + self.rr.label()[1:])
            self.f.after(500, self._tick)
        except tk.TclError:
            pass

    PEN_KEYS = {"8": "N", "2": "S", "4": "W", "6": "E", "7": "NW", "9": "NE", "1": "SW", "3": "SE",
                "0": "U", ".": "D", "+": "U", "-": "D"}

    def _key(self, e):
        rr = self.rr
        if not (rr.active and getattr(rr, "draw", False)):
            return None
        if isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Combobox, ttk.Spinbox, tk.Text)):
            return None
        if e.keysym == "BackSpace":
            self._undo()
            return "break"
        import sys
        from .macros import key_name
        win = sys.platform.startswith("win")
        nm = key_name(e.keysym, e.keycode, e.state, win, extended=bool(e.state & 0x20000) if win else True) or ""
        k = nm[len("Keypad "):] if nm.startswith("Keypad ") else (e.keysym if e.keysym in self.PEN_KEYS else None)
        d = self.PEN_KEYS.get(k or "")
        if not d:
            return None
        if not rr.step(d):
            self.f.bell()                             # no exit that way from here
        else:
            st = self.s.state
            me = st.room or (st.candidates[0] if st.candidates else None)
            self.m.scout = (rr.pen, me)               # the map follows the pen
            self.m.selected = rr.pen
        self.m.redraw()
        return "break"

    def _start(self, mode, walk=None):
        if self.rr.active:
            return
        if walk is not None:
            self.walk.set(walk)
        walk = self.walk.get()
        st = self.s.state
        at = st.room if walk else (self.m.selected or (self.m.scout[0] if self.m.scout else None) or st.room)
        err = self.rr.start_rec(mode, at=at, draw=not walk)
        if err:
            messagebox.showinfo("Record", err, parent=self.f.winfo_toplevel())
            return
        self.rr.on_change = self.m.redraw
        self._layout()
        self.m.redraw()
        # how it works, said once as it starts (Dan, 2026-11-01: "I don't know how this loop recording works")
        k = self.rr.start
        if walk:
            self.s.log(f"Recording a {mode} from {k[0]}/{k[1]} (your room): walk it in the game — the number pad or "
                       "typed directions — and every room you reach is a step. "
                       + ("Come back round to the start, then " if mode == "loop" else "Then ")
                       + "click ■ Stop / Save. ↶ Undo step drops the last one.")
            return
        self.s.log(f"Drawing a {mode} from {k[0]}/{k[1]} (the room you clicked, or yours): walk it on this map with the "
                   "number pad — 8 n, 2 s, 4 w, 6 e, 7/9/1/3 the diagonals, 0 up, . down, Backspace undoes. Nothing is "
                   "sent to the game. "
                   + ("Come back round to the start, then " if mode == "loop" else "Then ")
                   + "click ■ Stop / Save.")
        try:
            self.m.focus_set()                        # so the number pad lands here
        except tk.TclError:
            pass

    def _undo(self):
        if not self.rr.undo():
            self.f.bell()
        self.m.redraw()

    def _cancel(self):
        if self.rr.steps() and not messagebox.askyesno("Record", "Throw this recording away?",
                                                       parent=self.f.winfo_toplevel()):
            return
        self.rr.cancel()
        self.m.redraw()

    def _save(self):
        from .pathbuilder import save_new_path
        rr, top = self.rr, self.f.winfo_toplevel()
        title = "Record Loop" if rr.mode == "loop" else "Record Path"
        if not rr.steps():
            if messagebox.askyesno(title, "Nothing recorded yet. Stop recording?", parent=top):
                rr.cancel()
            return
        if rr.mode == "loop" and not rr.back_at_start():
            k = rr.start
            go_on = messagebox.askyesno(title, f"Not back at start ({k[0]}/{k[1]} "
                                               f"{self.s.world.room(k).name}).\n\nKeep recording and walk back to it?\n"
                                               "(No throws the recording away.)", parent=top)
            if not go_on:
                if messagebox.askyesno(title, "Throw the recording away?", parent=top):
                    rr.cancel()
                    self.m.redraw()
            return
        end = rr.rooms[-1]
        er = self.s.world.room(end)
        sr = self.s.world.room(rr.start)
        default = (f"{_area(self.s.world, rr.start)} loop" if rr.mode == "loop" else
                   f"{sr.name.split(',')[0] if sr else 'Here'} to {er.name.split(',')[-1].strip() if er else 'there'}")
        name = simpledialog.askstring(title, "Name it:", initialvalue=default, parent=top)
        if not name:
            return
        mp, err = rr.build(name.strip())
        if not mp:
            messagebox.showinfo(title, err, parent=top)
            return
        if save_new_path(self.app, mp, top, title):
            rr.finish()
            self.m.redraw()
