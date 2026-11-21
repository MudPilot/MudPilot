"""Path builder: walk the MME map with the number pad to draw a MegaMUD path or loop — nothing
is sent to the game.

  8 n   7 nw   9 ne   4 w   6 e   1 sw   2 s   3 se   0 up   . down      Backspace = undo

The map follows the "pen" as you walk (your trail is drawn in gold, the start in blue).
End where you started and it's a loop; end anywhere else and it's a path. You can also type a
room and "Route there" to fill in a long stretch automatically. "Add command" puts a command of your own
in (dig, search, a spell…): it's sent in that room before the next move — on a loop, ones at the end go
before the first step, so every lap does them. Only commands, no moves: a loop that stays in this room
and repeats them (digging for treasure). The window stays on top so the
map stays in view. Saved as a normal MegaMUD .mp file (works in MegaMUD too).
"""
from __future__ import annotations

import re
import sys
import tkinter as tk
from tkinter import ttk, messagebox

from .megamud_files import path_from_route
from .worlddb import DIR_WORDS

KEY_DIRS = {"8": "N", "2": "S", "4": "W", "6": "E", "7": "NW", "9": "NE", "1": "SW", "3": "SE",
            "0": "U", ".": "D"}
SHORT = {"N": "n", "S": "s", "E": "e", "W": "w", "NE": "ne", "NW": "nw", "SE": "se", "SW": "sw",
         "U": "u", "D": "d"}


def parse_room(text):
    m = re.match(r"^\s*(\d+)\s*/\s*(\d+)\s*$", text or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def route_to_mpath(world, start, route, name=""):
    """(MPath, "") from a start room and a route of Exits and commands (a command goes before the move after it;
    on a loop, ones at the end go before the first step) — or (None, why not). The Path builder and the map's
    Record Path / Record Loop both save through this."""
    exits = [x for x in route if not isinstance(x, str)]
    if not exits:
        if not route or not start:
            return None, "Walk a step or add a command first."
        # only commands: a loop that stays in this room (dig, dig, dig… — you can't walk at 430% anyway)
        from .megamud_files import MPath, Step
        r = world.room(start)
        return MPath(name or "New loop", "MudPilot", r.mega_hash, r.mega_hash,
                     start_label=r.name, end_label=r.name, resolved=True, resolve_note="built from MME",
                     steps=[Step(r.mega_hash, 0, "", list(route), start, start)]), ""
    mp = path_from_route(world, start, exits, name=name or "New path")
    # commands go in front of the move that follows them (MegaMUD's [cmd] on a step)
    pending, k, before = [], 0, {}
    for x in route:
        if isinstance(x, str):
            pending.append(x)
        else:
            if pending:
                before[k] = pending
            pending = []
            k += 1
    if pending:
        if exits[-1].to != start:
            return None, ("A path can't end on a command — walk one more step after it "
                          "(on a loop they go before the first step).")
        before[0] = pending + before.get(0, [])
    # path_from_route may add steps (walk to a lever and back): line the moves up by where they start
    idx, j = {}, 0
    for i, ex in enumerate(exits):
        frm = start if i == 0 else exits[i - 1].to
        while j < len(mp.steps) and not (mp.steps[j].room == frm and mp.steps[j].dest == ex.to):
            j += 1
        idx[i] = j if j < len(mp.steps) else None
        j += 1
    for i, cmds in before.items():
        n = idx.get(i)
        if n is None:
            continue
        mp.steps[n].pre = list(cmds) + list(mp.steps[n].pre or [])
    return mp, ""


def ask_folder(parent, session, title, why, initial=""):
    """'Which area folder?' — an editable list of the folders your paths are in. The name, or None (cancelled)."""
    from .areafolder import folders
    d = tk.Toplevel(parent)
    d.title(title)
    d.transient(parent)
    d.attributes("-topmost", True)
    fr = ttk.Frame(d, padding=12)
    fr.pack(fill="both", expand=True)
    ttk.Label(fr, text=why, wraplength=380, justify="left").pack(anchor="w")
    v = tk.StringVar(value=initial)
    cb = ttk.Combobox(fr, textvariable=v, values=folders(session), width=36)
    cb.pack(fill="x", pady=8)
    cb.focus_set()
    out = {"v": None}

    def ok(e=None):
        if v.get().strip():
            out["v"] = v.get().strip()
            d.destroy()
    bf = ttk.Frame(fr)
    bf.pack(fill="x")
    ttk.Button(bf, text="OK", style="Accent.TButton", command=ok).pack(side="right")
    ttk.Button(bf, text="Cancel", command=d.destroy).pack(side="right", padx=6)
    cb.bind("<Return>", ok)
    d.grab_set()
    d.wait_window()
    return out["v"]


def save_new_path(app, mp, parent, title, folder=None) -> bool:
    """Save a path/loop you made into the area folder its start room belongs in (the one your other paths around
    there use — Dan's Tierra del Fuego digging loop went into a 'MudPilot' folder), asking when that's not known."""
    from .areafolder import folder_for, area_name
    s = app.s
    start = mp.steps[0].room if mp.steps else None
    folder = folder or folder_for(s, start)
    if not folder:
        where = f"{start[0]}/{start[1]} {area_name(s.world, start)}" if start else "this room"
        folder = ask_folder(parent, s, title, f"Which area folder should '{mp.title}' go in? Nothing around "
                                              f"{where} is in one yet — pick one, or type a new name.")
        if not folder:
            return False
    mp.start_group = folder
    if mp.end_group in ("", "MudPilot") or mp.is_loop:
        mp.end_group = folder
    safe = re.sub(r"[^\w\- ]", "", mp.title).strip().replace(" ", "_")[:40] or "path"
    fn = safe + ".mp"
    if any(p.filename and p.filename.lower().endswith(fn.lower()) for p in s.paths):
        if not messagebox.askyesno(title, f"{fn} exists. Replace it?", parent=parent):
            return False
    s.save_path(mp, fn)
    app.refresh_paths()
    kind = "loop" if mp.is_loop else "path"
    s.log(f"Saved {kind} '{mp.title}' ({len(mp.steps)} steps) as {fn} in {folder}")
    messagebox.showinfo(title, f"Saved {kind} '{mp.title}' — {len(mp.steps)} steps, in the {folder} folder.\n"
                               f"It's under {'Loops' if mp.is_loop else 'Paths'} (works in MegaMUD too).", parent=parent)
    return True


class PathBuilder(ttk.Frame):
    def __init__(self, master, app):
        super().__init__(master, padding=10)
        self.app, self.s = app, app.s
        self.start = None
        self.route: list = []          # list[Exit], or a str for a command you typed ('dig')
        top = ttk.Frame(self)
        top.pack(fill="x")
        ttk.Label(top, text="Name").pack(side="left")
        self.name = tk.StringVar(value="New path")
        ttk.Entry(top, textvariable=self.name, width=26).pack(side="left", padx=4)
        ttk.Button(top, text="Start here (my room)", command=self.start_here).pack(side="left", padx=(8, 0))
        self.picking = tk.BooleanVar(value=False)
        ttk.Checkbutton(top, text="…or double-click the start on the Map", variable=self.picking,
                        command=self._pick_mode).pack(side="left", padx=6)
        mid = ttk.Frame(self)
        mid.pack(fill="both", expand=True, pady=(8, 0))
        # compass / number pad
        pad = ttk.LabelFrame(mid, text="Walk (number pad)", padding=6)
        pad.pack(side="left", fill="y")
        grid = (("7", "nw"), ("8", "n"), ("9", "ne"), ("4", "w"), (None, ""), ("6", "e"),
                ("1", "sw"), ("2", "s"), ("3", "se"))
        for i, (k, lbl) in enumerate(grid):
            if k is None:
                ttk.Label(pad, text="●", anchor="center", width=5).grid(row=i // 3, column=i % 3)
                continue
            ttk.Button(pad, text=f"{lbl}\n{k}", width=5, command=lambda k=k: self.step_key(k)).grid(
                row=i // 3, column=i % 3, padx=1, pady=1)
        ttk.Button(pad, text="down\n.", width=5, command=lambda: self.step_key(".")).grid(row=3, column=2, padx=1, pady=1)
        ttk.Button(pad, text="up\n0", width=5, command=lambda: self.step_key("0")).grid(row=3, column=0, padx=1, pady=1)
        ttk.Button(pad, text="undo\n⌫", width=5, command=self.undo).grid(row=3, column=1, padx=1, pady=1)
        rt = ttk.Frame(pad)
        rt.grid(row=4, column=0, columnspan=3, pady=(10, 0), sticky="we")
        ttk.Label(rt, text="Route to room").pack(anchor="w")
        self.room_q = tk.StringVar()
        e = ttk.Entry(rt, textvariable=self.room_q, width=18)
        e.pack(fill="x")
        e.bind("<Return>", lambda ev: self.route_to())
        ttk.Button(rt, text="Route there", command=self.route_to).pack(fill="x", pady=(3, 0))
        ttk.Label(rt, text="Command here").pack(anchor="w", pady=(10, 0))
        self.cmd_q = tk.StringVar()
        ce = ttk.Entry(rt, textvariable=self.cmd_q, width=18)
        ce.pack(fill="x")
        ce.bind("<Return>", lambda ev: self.add_cmd())
        ttk.Button(rt, text="Add command", command=self.add_cmd).pack(fill="x", pady=(3, 0))
        ttk.Button(rt, text="Clear", command=self.clear).pack(fill="x", pady=(10, 0))
        # steps
        sf = ttk.LabelFrame(mid, text="Steps", padding=6)
        sf.pack(side="left", fill="both", expand=True, padx=(8, 0))
        cols = ("n", "dir", "room")
        self.steps = ttk.Treeview(sf, columns=cols, show="headings", height=14)
        for c, t, w in (("n", "#", 40), ("dir", "Move", 70), ("room", "To", 300)):
            self.steps.heading(c, text=t)
            self.steps.column(c, width=w, anchor="w")
        sb = ttk.Scrollbar(sf, orient="vertical", command=self.steps.yview)
        self.steps.configure(yscrollcommand=sb.set)
        self.steps.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        bot = ttk.Frame(self)
        bot.pack(fill="x", pady=(8, 0))
        self.info = ttk.Label(bot, text="Pick a start room.", style="Head.TLabel")
        self.info.pack(side="left")
        ttk.Button(bot, text="Save", style="Accent.TButton", command=self.save).pack(side="right")
        ttk.Button(bot, text="Walk it now", command=self.walk).pack(side="right", padx=6)
        self.hint = ttk.Label(self, text="", style="Muted.TLabel")
        self.hint.pack(anchor="w", pady=(4, 0))
        tl = self.winfo_toplevel()
        tl.bind("<Key>", self._key, add="+")
        try:
            tl.attributes("-topmost", True)      # stays on top so you can watch the map while drawing
        except tk.TclError:
            pass
        from . import mapview
        mapview.MapView.overlay = self.overlay
        if self.s.state.room:
            self.start_here()
        self.rebuild()

    # ------------------------------------------------------------ map hookup
    def overlay(self):
        """What the Map should show while drawing: centred on the pen, with the trail."""
        if not self.start:
            return None
        trail = [self.start] + [ex.to for ex in self.exits()]
        return {"center": trail[-1], "trail": trail, "start": self.start}

    def _map_redraw(self):
        from . import mapview
        for m in list(mapview.MapView.instances):
            try:
                m.redraw()
            except tk.TclError:
                pass

    def destroy(self):
        from . import mapview
        if getattr(mapview.MapView, "overlay", None) == self.overlay:
            mapview.MapView.overlay = None
        if getattr(self.app, "_map_pick", None) == self._picked:
            self.app._map_pick = None
        super().destroy()
        self._map_redraw()

    def _pick_mode(self):
        self.app._map_pick = self._picked if self.picking.get() else None

    def _picked(self, key):
        self.picking.set(False)
        self.app._map_pick = None
        self.set_start(tuple(key))

    # ------------------------------------------------------------ drawing
    def start_here(self):
        if self.s.state.room:
            self.set_start(self.s.state.room)
        else:
            self.hint.configure(text="Your room isn't known — press Enter in the game, or double-click a start on the Map.")

    def set_start(self, key):
        if self.route and not messagebox.askyesno("Path builder", "Start over from this room?", parent=self):
            return
        self.start, self.route = tuple(key), []
        self.rebuild()

    def exits(self):
        return [x for x in self.route if not isinstance(x, str)]

    def here(self):
        ex = self.exits()
        return ex[-1].to if ex else self.start

    def add_cmd(self):
        c = self.cmd_q.get().strip()
        if not c or not self.here():
            if not self.here():
                self.hint.configure(text="Pick a start room first.")
            return
        self.route.append(c)
        self.cmd_q.set("")
        self.steps.focus_set()               # number pad walks again
        self.rebuild()

    def _key(self, e):
        if isinstance(e.widget, (tk.Entry, ttk.Entry, ttk.Combobox, ttk.Spinbox)):
            return None                      # typing a name / room: keys are just text
        from .macros import key_name
        win = sys.platform.startswith("win")
        name = key_name(e.keysym, e.keycode, e.state, win, extended=bool(e.state & 0x20000) if win else True)
        if name and name.startswith("Keypad "):
            k = name.split(" ", 1)[1]
            if k in KEY_DIRS:
                self.step_key(k)
                return "break"
        if e.keysym == "BackSpace":
            self.undo()
            return "break"
        return None

    def step_key(self, k):
        d = KEY_DIRS.get(k)
        here = self.here()
        if not here:
            self.hint.configure(text="Pick a start room first.")
            return
        r = self.s.world.room(here)
        ex = r.exits.get(d) if r else None
        if not ex or ex.to not in self.s.world.rooms:
            self.bell()
            self.hint.configure(text=f"No exit {DIR_WORDS.get(d, d)} from {r.name if r else here}.")
            return
        note = ""
        if ex.kind not in ("normal",):
            note = f"  ({ex.etype.strip('()') or ex.kind})"
        self.route.append(ex)
        self.hint.configure(text=f"{DIR_WORDS.get(d, d)} → {ex.to[0]}/{ex.to[1]} {self.s.world.room(ex.to).name}{note}")
        self.rebuild()

    def undo(self):
        if self.route:
            self.route.pop()
            self.rebuild()

    def clear(self):
        self.route = []
        self.rebuild()

    def route_to(self):
        q = self.room_q.get().strip()
        here = self.here()
        if not q or not here:
            return
        w = self.s.world
        key = parse_room(q)
        target = key if key and w.room(key) else None
        if not target:
            hits = w.search_rooms(q)[:200] if w.loaded else []
            best = None
            for r in hits:
                leg = w.route(here, r.key, level=self.s.state.level or None)
                if leg is not None and (best is None or len(leg) < len(best[1])):
                    best = (r.key, leg)
            if not best:
                messagebox.showinfo("Path builder", f"No reachable room matches '{q}'.", parent=self)
                return
            target, leg = best
        else:
            leg = w.route(here, target, level=self.s.state.level or None)
        if leg is None:
            messagebox.showinfo("Path builder", "No way there through MME's exits.", parent=self)
            return
        self.route += leg
        self.room_q.set("")
        self.steps.focus_set()               # number pad walks again
        self.rebuild()

    def is_loop(self):
        return bool(self.route) and self.here() == self.start

    def rebuild(self):
        w = self.s.world
        self.steps.delete(*self.steps.get_children())
        for i, ex in enumerate(self.route, start=1):
            if isinstance(ex, str):
                h = self._here_at(i)
                self.steps.insert("", "end", values=(i, ex, f"(command, in {h[0]}/{h[1]})" if h else "(command)"))
                continue
            r = w.room(ex.to)
            mv = ex.text_command if ex.kind == "text" and getattr(ex, "text_command", "") else SHORT.get(ex.dir, ex.dir)
            self.steps.insert("", "end", values=(i, mv, f"{ex.to[0]}/{ex.to[1]}  {r.name if r else '?'}"))
        kids = self.steps.get_children()
        if kids:
            self.steps.see(kids[-1])
        if not self.start:
            self.info.configure(text="Pick a start room.")
        elif not self.route:
            r = w.room(self.start)
            self.info.configure(text=f"Start: {self.start[0]}/{self.start[1]} {r.name if r else ''} — walk with the number pad")
        else:
            kind = "LOOP (back at the start)" if self.is_loop() else "PATH"
            h = self.here()
            nc = sum(isinstance(x, str) for x in self.route)
            self.info.configure(text=f"{kind} · {len(self.route) - nc} steps{f' + {nc} commands' if nc else ''} · "
                                     f"now at {h[0]}/{h[1]} {w.room(h).name}")
        self._map_redraw()

    # ------------------------------------------------------------ save / walk
    def _here_at(self, n):
        ex = [x for x in self.route[:n] if not isinstance(x, str)]
        return ex[-1].to if ex else self.start

    def build(self):
        mp, err = route_to_mpath(self.s.world, self.start, self.route, self.name.get().strip())
        if err:
            messagebox.showinfo("Path builder", err, parent=self)
        return mp

    def save(self):
        mp = self.build()
        if mp:
            save_new_path(self.app, mp, self, "Path builder")

    def walk(self):
        mp = self.build()
        if not mp:
            return
        here = self.s.state.room
        if here and here != self.start:
            self.s.bot.goto(self.start, then=mp, ask=getattr(self.app, "ask_route", None))
        else:
            self.s.bot.start_path(mp, loop=mp.is_loop)
