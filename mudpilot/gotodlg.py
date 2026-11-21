"""MegaMUD-style Goto and Loop pickers: one window, area folders, searchable.

Goto lists the rooms MegaMUD knows (your Rooms.md, imported with your paths), one per room number,
plus rooms you add (Add this room; right-click to rename / remove), grouped by area. Typing searches them — and every MME room by name
or map/room number, so you can go anywhere. Loop lists only the loops, grouped the same way.
"""
from __future__ import annotations

import json
import os
import re
import tkinter as tk
from tkinter import ttk

RECENT_N = 5


def _recent_path(s):
    from . import config
    return os.path.join(config.board_dir(s.settings.board), "recent_goto.json")


def recent_load(s) -> list:
    """Where you've gone and what you've looped lately, newest first: [["room", [m, r]] | ["loop", title], …]."""
    try:
        data = json.load(open(_recent_path(s), encoding="utf-8"))
        return [x for x in data if isinstance(x, list) and len(x) == 2][:RECENT_N]
    except (OSError, ValueError):
        return []


def recent_add(s, kind, val):
    """A Go to or a loop you started: to the top of the Goto list (Dan, 2026-11-02: "the last 5 spots at the top
    that we've gone too or looped")."""
    ent = [kind, list(val) if kind == "room" else str(val)]
    items = [ent] + [x for x in recent_load(s) if x != ent]
    try:
        os.makedirs(os.path.dirname(_recent_path(s)), exist_ok=True)
        json.dump(items[:RECENT_N], open(_recent_path(s), "w", encoding="utf-8"))
    except OSError:
        pass


def loop_entries(s):
    """Every loop as (area folder, label, ("loop", mp) | ("routine", name)). Both the toolbar's Run a loop… and
    the Paths tab's Loops list come from here, so they list the same things the same way (Dan, 2026-11-04)."""
    for mp in s.paths:
        if mp.is_loop:
            yield mp.start_group or "Loops", mp.title or mp.start_label or "loop", ("loop", mp)
    # not a recorded loop: MudPilot's own routine (peruse.py) — Dan searched 'book' and found nothing
    yield "Golden Spire", "Peruse books (Secret Library, 12/2248)", ("routine", "peruse")


def loop_matches(q, grp, label, item) -> bool:
    if not q:
        return True
    mp = item[1] if item[0] == "loop" else None
    return q in label.lower() or q in grp.lower() or bool(mp and q in os.path.basename(mp.filename or "").lower())


class Picker(tk.Toplevel):
    def __init__(self, app, mode="goto"):
        super().__init__(app.root)
        self.app, self.s, self.mode = app, app.s, mode
        self.title("Goto location…" if mode == "goto" else "Run a loop…")
        self.geometry("560x560")
        self.configure(background="#151a21")
        self.transient(app.root)
        self.q = tk.StringVar()
        e = ttk.Entry(self, textvariable=self.q)
        e.pack(fill="x", padx=8, pady=(8, 4))
        e.focus_set()
        e.bind("<Return>", lambda ev: self.go())
        e.bind("<Down>", lambda ev: (self.tree.focus_set(), self._first()))
        self.q.trace_add("write", lambda *a: self._schedule())
        fr = ttk.Frame(self)
        fr.pack(fill="both", expand=True, padx=8)
        self.tree = ttk.Treeview(fr, show="tree", selectmode="browse")
        sb = ttk.Scrollbar(fr, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda ev: self.go())
        self.tree.bind("<Return>", lambda ev: self.go())
        self.tree.bind("<KeyPress>", self._type_jump)
        self._typed = ("", 0.0)
        b = ttk.Frame(self)
        b.pack(fill="x", padx=8, pady=8)
        if mode == "goto":
            ttk.Button(b, text="Go", style="Accent.TButton", command=self.go).pack(side="left")
        else:
            ttk.Button(b, text="Run", style="Accent.TButton", command=self.go).pack(side="left")
        if mode == "goto":
            ttk.Button(b, text="Preview route…", command=self.preview).pack(side="left", padx=(6, 0))
        ttk.Button(b, text="Cancel", command=self.destroy).pack(side="left", padx=6)
        if mode == "goto":
            ttk.Button(b, text="Add this room", command=self.add_here).pack(side="left", padx=(0, 6))
            self.tree.bind("<Button-3>", self._menu)
        self.note = ttk.Label(b, text="", style="Muted.TLabel")
        self.note.pack(side="left", padx=8)
        self.bind("<Escape>", lambda ev: self.destroy())
        self._items = {}
        self._after = None
        self.fill()

    # ---- your list: add the room you're in, rename or remove an entry (right-click)
    def add_here(self):
        from tkinter import simpledialog
        k = self.s.state.room
        if not k:
            self.note.configure(text="Not sure which room you're in — press Enter (look) first")
            return
        r = self.s.world.room(k)
        nm = simpledialog.askstring("Add this room", f"Name for {k[0]}/{k[1]}:", initialvalue=r.name if r else "",
                                    parent=self)
        if nm and nm.strip():
            grp = simpledialog.askstring("Add this room", "Folder (area):", initialvalue="My places", parent=self)
            self.s.place_add(k, nm.strip(), (grp or "My places").strip() or "My places")
            self.fill()

    def _menu(self, ev):
        iid = self.tree.identify_row(ev.y)
        item = self._items.get(iid)
        if not item or item[0] != "room":
            return
        self._select(iid)
        key = item[1]
        m = tk.Menu(self, tearoff=0)
        m.add_command(label="Go", command=self.go)
        m.add_command(label="Rename…", command=lambda: self._rename(iid, key))
        m.add_command(label="Remove from the list", command=lambda: (self.s.place_remove(key), self.fill()))
        m.tk_popup(ev.x_root, ev.y_root)

    def _rename(self, iid, key):
        from tkinter import simpledialog
        cur = self.tree.item(iid, "text").strip()
        cur = cur.rsplit(f"-{key[0]} {key[1]}", 1)[0]
        nm = simpledialog.askstring("Rename", f"Name for {key[0]}/{key[1]}:", initialvalue=cur, parent=self)
        if nm and nm.strip():
            self.s.place_rename(key, nm.strip())
            self.fill()

    def _schedule(self):
        if self._after:
            self.after_cancel(self._after)
        self._after = self.after(200, self.fill)

    def _first(self):
        for g in self.tree.get_children():
            kids = self.tree.get_children(g)
            if kids:
                self.tree.selection_set(kids[0])
                self.tree.focus(kids[0])
                self.tree.see(kids[0])
                return

    def _entries(self):
        if self.mode == "goto":
            mine = set()
            for grp, name, key in self.s.known_rooms():
                mine.add(tuple(key))
                yield grp, f"{name}-{key[0]} {key[1]}", ("room", key)
            # built in from MME (Dan, 2026-10-30): every shop and NPC, without MegaMUD's Rooms.md
            if self.s.world.loaded:
                for grp, name, key in self.s.world.places():
                    if key not in mine:
                        yield f"MME {grp.lower()}", f"{name}-{key[0]} {key[1]}", ("room", key)
        else:
            yield from loop_entries(self.s)

    def fill(self):
        q = self.q.get().strip().lower()
        self.tree.delete(*self.tree.get_children())
        self._items = {}
        groups = {}
        n = 0
        for grp, label, item in sorted(self._entries(), key=lambda x: (x[0].lower(), x[1].lower())):
            if self.mode == "goto" and q and q not in label.lower() and q not in grp.lower() or                     self.mode != "goto" and not loop_matches(q, grp, label, item):
                continue
            gid = groups.get(grp)
            if gid is None:
                gid = groups[grp] = self.tree.insert("", "end", text=f"📁 {grp}", open=bool(q))
            iid = self.tree.insert(gid, "end", text=f"   {label}")
            self._items[iid] = item
            n += 1
        # a room number typed ('12/2002', '12 2002', 'map 12 room 2002', or just '2002' = on this map): first
        # in the list, so Enter goes straight there
        if self.mode == "goto" and q and len(q) >= 3:
            me = (self.s.settings.my_name or "").lower()
            mates = [n for n in self.s.state.party if n.lower() != me and n.lower().startswith(q)]
            if mates:
                gid = self.tree.insert("", 0, text="🧭 Walk to a party member (asks them @where)", open=True)
                for n in mates:
                    iid = self.tree.insert(gid, "end", text=f"   {n}")
                    self._items[iid] = ("player", n)
                self._select(self.tree.get_children(gid)[0])
                self.note.configure(text=f"Enter = find {mates[0]} and walk there")
                return
        if self.mode == "goto" and self.s.world.loaded:
            keys = self._typed_rooms(q)
            if keys:
                gid = self.tree.insert("", 0, text="📍 Room number", open=True)
                first = None
                for k in keys:
                    r = self.s.world.room(k)
                    iid = self.tree.insert(gid, "end", text=f"   {k[0]}/{k[1]}  {r.name if r else ''}")
                    self._items[iid] = ("room", k)
                    first = first or iid
                self.note.configure(text=f"Enter = go to {keys[0][0]}/{keys[0][1]}")
                self._select(first)
                return
        # Goto: a monster's name finds where it lives (Dan, 2026-10-30: 'sleazy shopkeeper')
        if self.mode == "goto" and len(q) >= 3 and self.s.world.loaded:
            w = self.s.world
            rows = [(m, k, how) for m in w.search_monsters(q, limit=15) for k, how in w.monster_rooms(m["num"])]
            if rows:
                gid = self.tree.insert("", "end", text="👹 Monsters matching", open=True)
                for m, k, how in rows[:60]:
                    r = w.room(k)
                    iid = self.tree.insert(gid, "end", text=f"   {m['name']} — {r.name if r else ''}-{k[0]} {k[1]}"
                                                            + ("" if how == "stands here" else f"  ({how})"))
                    self._items[iid] = ("room", k)
                    n += 1
        # Goto: searching also finds any MME room, even ones MegaMUD never named
        extra = 0
        if self.mode == "goto" and len(q) >= 3 and self.s.world.loaded:
            listed = {it[1] for it in self._items.values() if it[0] == "room"}
            hits = [r for r in self.s.world.search_rooms(q, limit=150) if r.key not in listed]
            extra = len(hits)
            if hits:
                gid = self.tree.insert("", "end", text="🔎 All MME rooms matching", open=True)
                for r in hits:
                    iid = self.tree.insert(gid, "end", text=f"   {r.name}-{r.key[0]} {r.key[1]}")
                    self._items[iid] = ("room", r.key)
        if self.mode == "goto" and not q:
            self._recent()
        if self.mode == "goto" and not n and not q:
            self.note.configure(text="No MegaMUD rooms yet — import your paths folder (Rooms.md comes with it), or type to search.")
        else:
            self.note.configure(text=f"{n} {'rooms' if self.mode == 'goto' else 'loops'}" + (" match" if q else "")
                                + (f" · {extra} more in MME" if extra else ""))
        if q:
            self._first()
        else:
            self._point_here()

    def _recent(self):
        """The last 5 places you went and loops you ran, at the top."""
        rows = []
        for kind, val in recent_load(self.s):
            if kind == "room":
                k = tuple(val)
                r = self.s.world.room(k)
                rows.append((f"{r.name if r else 'room'}-{k[0]} {k[1]}", ("room", k)))
            else:
                mp = next((p for p in self.s.paths if p.is_loop and (p.title or p.start_label) == val), None)
                if mp is not None:
                    rows.append((f"⟳ {val}  (loop)", ("loop", mp)))
        if not rows:
            return
        gid = self.tree.insert("", 0, text="🕘 Recent", open=True)
        for label, item in rows:
            iid = self.tree.insert(gid, "end", text=f"   {label}")
            self._items[iid] = item

    def _typed_rooms(self, q):
        import re
        w = self.s.world
        m = re.fullmatch(r"(?:map\s*)?(\d{1,3})\s*(?:/|,|-|\s|\s*room\s*)\s*(\d{1,5})", q.strip(), re.I)
        if m:
            k = (int(m.group(1)), int(m.group(2)))
            return [k] if k in w.rooms else []
        m = re.fullmatch(r"(?:room\s*)?#?(\d{1,5})", q.strip(), re.I)
        if not m:
            return []
        n = int(m.group(1))
        here = self.s.state.room
        keys = [k for k in w.rooms if k[1] == n]
        keys.sort(key=lambda k: (k[0] != (here[0] if here else -1), k[0]))   # this map first
        return keys[:12]

    def _point_here(self):
        """No search typed: open on where you're standing — the known room you're in (Goto),
        or loops that start here, then loops that pass through here (Loop)."""
        here = self.s.state.room
        if not here:
            return
        if self.mode == "goto":
            for iid, item in self._items.items():
                if item == ("room", here):
                    parent = self.tree.parent(iid)
                    self.tree.item(parent, open=True)
                    self._select(iid)
                    self.note.configure(text=self.note.cget("text") + " · you're here")
                    return
            return
        starts = [mp for mp in self.s.paths if mp.is_loop and mp.steps and mp.steps[0].room == here]
        through = [mp for mp in self.s.paths if mp.is_loop and mp not in starts and any(st.room == here for st in mp.steps)]
        if not starts and not through:
            return
        gid = self.tree.insert("", 0, text="📍 Loops from where you're standing", open=True)
        first = None
        for mp in starts + through:
            iid = self.tree.insert(gid, "end", text=f"   {mp.title}" + ("" if mp in starts else "  (passes through here)"))
            self._items[iid] = ("loop", mp)
            first = first or iid
        self._select(first)

    @staticmethod
    def _folder_name(text: str) -> str:
        return re.sub(r"^\W+", "", text or "").strip().lower()

    def _type_jump(self, ev):
        """Click in the list and type a letter: jump to the first folder starting with it — R for Rugged Plateau —
        instead of scrolling and scrolling (Dan, 2026-11-20). Type more letters quickly to narrow it ('ru'); the
        same letter again goes on to the next folder starting with it."""
        ch = ev.char or ""
        if len(ch) != 1 or not (ch.isalnum() or ch in " '-") or (ev.state & 0x4):
            return None
        import time as _t
        now = _t.time()
        buf, at = self._typed
        buf = (buf + ch.lower()) if now - at < 1.0 else ch.lower()
        self._typed = (buf, now)
        folders = list(self.tree.get_children(""))
        if not folders:
            return "break"
        sel = self.tree.focus()
        cur = sel if sel in folders else (self.tree.parent(sel) if sel else "")
        start = folders.index(cur) if cur in folders else -1
        if len(set(buf)) == 1 and len(buf) > 1:
            buf = buf[0]                                 # 'rrr' = the third folder starting with r
        order = folders[start + 1:] + folders[:start + 1] if len(buf) == 1 else folders
        hit = next((f for f in order if self._folder_name(self.tree.item(f, "text")).startswith(buf)), None)
        if hit:
            self.tree.see(folders[-1])                  # (then back up: the folder lands at the top of the list)
            self._select(hit)
        return "break"

    def _select(self, iid):
        self.tree.selection_set(iid)
        self.tree.focus(iid)
        self.tree.see(iid)

    def go(self):
        sel = self.tree.selection()
        if not sel or sel[0] not in self._items:
            self._first()
            sel = self.tree.selection()
            if not sel or sel[0] not in self._items:
                return
        kind, val = self._items[sel[0]]
        bot = self.s.bot
        try:
            from . import uilog
            label = self.tree.item(sel[0], "text").strip()
            uilog.you(f"picked '{label}' in {'Goto' if self.mode == 'goto' else 'Loop'}"
                      + (f" (searched '{self.q.get().strip()}')" if self.q.get().strip() else ""))
        except Exception:
            pass
        if kind == "room":
            self.app.goto_room(val)
        elif kind == "routine":
            self.s.log(bot.peruse.start())
        elif kind == "player":
            cb = self.s.comeback
            cb._ask_where(val)
            cb.fetch["no_invite"] = True
            self.s.log(f"Goto: asking {val} where they are, then walking there")
        else:
            recent_add(self.s, "loop", val.title or val.start_label)
            here = self.s.state.room
            if here and val.resolved and val.steps and val.steps[0].room and not any(st.room == here for st in val.steps):
                self.app.plan_route(lambda ask: bot.goto(val.steps[0].room, then=val, ask=ask), "to the loop's start")
            else:
                bot.start_path(val, loop=True)
        self.destroy()

    def preview(self):
        """'Preview route…' (0.8.208, Dan): the way it would take, with rooms to strike off before going."""
        sel = self.tree.selection()
        if not sel or sel[0] not in self._items:
            self._first()
            sel = self.tree.selection()
        item = self._items.get(sel[0]) if sel else None
        if not item or item[0] != "room":
            self.note.configure(text="Pick a room to preview the way there")
            return
        from .routepreview import open_preview
        label = self.tree.item(sel[0], "text").strip()
        open_preview(self.app, tuple(item[1]), label)
        self.destroy()
