"""Route preview (0.8.208, Dan): before a Go to, see the way it would take — the rooms it passes, a run of rooms with
the same name shown once — and strike off any you don't like ('avoid Seher' → the way through the Negative Power
Plane; avoid that too → round by Arlysia and across the lake). 'Go this way' walks it; the rooms you struck off
count for that Go to only."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

NOTE_KINDS = {"normal": "", "": ""}


def exit_note(ex) -> str:
    """What's odd about this exit, short: a toll, a key, an item, a door, a spell, a teleport, a level gate."""
    kind = getattr(ex, "kind", "") or ""
    if kind in NOTE_KINDS:
        return ""
    t = (getattr(ex, "etype", "") or kind).strip()
    return t[:60]


def summarize(world, start, route) -> list:
    """[(name, [rooms], note)] — the start, then each room the route enters; consecutive rooms of one name are one
    row (their notes joined)."""
    rows = []

    def add(room, note):
        r = world.room(room) if room else None
        name = r.name if r else (f"{room[0]}/{room[1]}" if room else "?")
        if rows and rows[-1][0] == name:
            rows[-1][1].append(room)
            if note:
                rows[-1][2].append(note)
        else:
            rows.append((name, [room], [note] if note else []))
    if start:
        add(tuple(start), "")
    for ex in route or []:
        add(tuple(ex.to), exit_note(ex))
    return [(n, rs, "; ".join(dict.fromkeys(ns))) for n, rs, ns in rows]


class RoutePreview(tk.Toplevel):
    def __init__(self, app, target, label=""):
        super().__init__(app.root)
        self.app, self.s = app, app.s
        self.target = tuple(target)
        self.avoid = set()
        self.route = None
        self.rows = []
        r = self.s.world.room(self.target)
        self.title(f"Route to {label or (r.name if r else '')} ({self.target[0]}/{self.target[1]})")
        self.geometry("620x520")
        top = ttk.Frame(self, padding=8)
        top.pack(fill="both", expand=True)
        self.note = ttk.Label(top, text="Working out the route…", wraplength=590, justify="left")
        self.note.pack(anchor="w", pady=(0, 6))
        cols = ("rooms", "where", "note")
        self.tree = ttk.Treeview(top, columns=cols, show="tree headings", selectmode="extended")
        self.tree.heading("#0", text="Room")
        self.tree.heading("rooms", text="×")
        self.tree.heading("where", text="Map/room")
        self.tree.heading("note", text="On the way in")
        self.tree.column("#0", width=230)
        self.tree.column("rooms", width=36, anchor="e")
        self.tree.column("where", width=80)
        self.tree.column("note", width=240)
        sb = ttk.Scrollbar(top, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="left", fill="y")
        self.tree.bind("<Double-1>", lambda e: self.avoid_selected())
        b = ttk.Frame(self, padding=(8, 0, 8, 8))
        b.pack(fill="x")
        ttk.Button(b, text="Avoid selected & find another way", command=self.avoid_selected).pack(side="left")
        self.clear_btn = ttk.Button(b, text="Clear avoided", command=self.clear_avoid, state="disabled")
        self.clear_btn.pack(side="left", padx=6)
        ttk.Button(b, text="Close", command=self.destroy).pack(side="right")
        self.go_btn = ttk.Button(b, text="Go this way", style="Accent.TButton", command=self.go, state="disabled")
        self.go_btn.pack(side="right", padx=6)
        self.after(50, self.replan)

    # ------------------------------------------------------------------ planning
    def replan(self):
        from . import bgplan
        bot, w = self.s.bot, self.s.world
        here = self.s.state.room
        if not here:
            self.note.configure(text="Not sure which room you're in yet — look around and try again.")
            return
        if getattr(bot, "_planning", False):
            self.after(500, self.replan)
            return
        self.note.configure(text="Working out the route…")
        self.go_btn.configure(state="disabled")
        avoid = frozenset(self.avoid)

        def fn(_ask):
            old = getattr(w, "user_avoid", None)
            w.user_avoid = avoid or None
            try:
                return here, bot.plan_route(here, self.target, None)
            finally:
                w.user_avoid = old

        def done(res, err):
            if not self.winfo_exists():
                return
            if err is not None:
                self.note.configure(text=f"Couldn't work out a route: {err}")
                return
            start, route = res
            self.show(start, route)
        bgplan.plan(self.s, fn, done=done, after=self.app.root.after)

    def show(self, start, route):
        self.tree.delete(*self.tree.get_children())
        self.route = route
        n_av = len({self.s.world.room(r).name if self.s.world.room(r) else r for r in self.avoid})
        av = f" Avoiding {n_av} place(s)." if self.avoid else ""
        if route is None:
            why = getattr(self.s.bot, "no_route_msg", "") or "no way found"
            self.note.configure(text=f"No route{' without the rooms you struck off' if self.avoid else ''}: {why}."
                                     f"{av} 'Clear avoided' to start over.")
            self.rows = []
            return
        self.rows = summarize(self.s.world, start, route)
        for i, (name, rooms, note) in enumerate(self.rows):
            k = rooms[0]
            where = f"{k[0]}/{k[1]}" if k else ""
            self.tree.insert("", "end", iid=str(i), text=name, values=(len(rooms) if len(rooms) > 1 else "", where,
                                                                        note))
        self.note.configure(text=f"{len(route)} rooms, {len(self.rows)} places.{av} Pick a place you'd rather not go "
                                 "through and 'Avoid' it (or double-click) — it finds another way.")
        self.go_btn.configure(state="normal")

    # ------------------------------------------------------------------ actions
    def avoid_selected(self):
        sel = [int(i) for i in self.tree.selection() if i.isdigit()]
        sel = [i for i in sel if 0 < i < len(self.rows) - 1] or [i for i in sel if 0 < i < len(self.rows)]
        if not sel:
            self.note.configure(text="Pick a place on the way (not where you're standing or where you're going).")
            return
        for i in sel:
            self.avoid |= {r for r in self.rows[i][1] if r and r != self.target}
        self.clear_btn.configure(state="normal")
        self.replan()

    def clear_avoid(self):
        self.avoid.clear()
        self.clear_btn.configure(state="disabled")
        self.replan()

    def go(self):
        bot = self.s.bot
        bot._trip_avoid = (self.target, frozenset(self.avoid)) if self.avoid else None
        if self.avoid:
            names = sorted({self.s.world.room(r).name for r in self.avoid if self.s.world.room(r)})
            self.s.log("Go to: staying out of " + ", ".join(names[:6]) + (" …" if len(names) > 6 else ""))
        self.destroy()
        self.app.goto_room(self.target)


def open_preview(app, target, label=""):
    try:
        return RoutePreview(app, target, label)
    except tk.TclError:
        return None
