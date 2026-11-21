"""Live map: lays out rooms around your position on a grid using exit directions
(breadth-first, same map number), highlights you, the active path and mobs."""
from __future__ import annotations

import tkinter as tk
import weakref
from collections import deque

VEC = {"N": (0, -1), "S": (0, 1), "E": (1, 0), "W": (-1, 0),
       "NE": (1, -1), "NW": (-1, -1), "SE": (1, 1), "SW": (-1, 1)}


class MapView(tk.Canvas):
    CELL = 34
    BOX = 16
    overlay = None                      # Path builder: callable → {"center", "trail", "start"} or None
    instances = weakref.WeakSet()       # every map on screen (main + pop-out)

    def __init__(self, master, session, on_goto=None, follow=True, **kw):
        super().__init__(master, background="#11151c", highlightthickness=0, **kw)
        self.s = session
        self.on_goto = on_goto
        self.follow = follow          # False (pop-out map): stays where you look until you press "Me"
        self.radius = 7
        self.grid_n = 0               # 20 / 30 / 50 = show that many rooms across; 0 = zoom with the wheel
        self._pos = {}
        self._center = None
        self.bind("<Configure>", lambda e: self.redraw())
        self.bind("<Double-Button-1>", self._dbl)
        self.bind("<Button-3>", self._scout)           # right-click: look around from that room
        self.scout = None                               # (room, your room when you clicked)
        MapView.instances.add(self)
        if not follow:                                  # pop-out map: walk it with the number pad / arrows
            self.bind("<Button-1>", lambda e: self.focus_set(), add="+")
            self.bind("<Key>", self._pan_key)
        self.on_click = None                            # the pop-out map's room panel: called with the room
        self.selected = None                            # …and that room gets a cyan outline
        self.bind("<ButtonRelease-1>", self._click, add="+")
        self.bind("<Motion>", self._hover)
        self.bind("<MouseWheel>", self._wheel)
        self.bind("<Button-4>", lambda e: self._zoom(1))
        self.bind("<Button-5>", lambda e: self._zoom(-1))
        self.tip = None
        self.highlight = None                           # Edit loop: these rooms show as the path
        self.badges = None                              # Edit loop: callable → {room: 'NA'…} drawn on the room

    def _wheel(self, e):
        self._zoom(1 if e.delta > 0 else -1)

    def _zoom(self, d):
        if self.grid_n:
            return                     # fixed 20/30/50 grid
        self.CELL = max(18, min(60, self.CELL + d * 4))
        self.BOX = max(8, int(self.CELL * 0.47))
        self.redraw()

    # where to put a room that's up/down (or across a map change) — the nearest free spot that way
    VERT = {"U": [(1, -1), (0, -1), (-1, -1), (1, 0), (-1, 0), (2, -1), (2, -2)],
            "D": [(-1, 1), (0, 1), (1, 1), (-1, 0), (1, 0), (-2, 1), (-2, 2)]}

    def layout(self, center):
        """Rooms around `center` on a grid by exit direction. Up/down exits (and exits into another
        map) don't have a compass spot, so they go in the nearest free cell and get a ▲/▼ link —
        a climb like Frozen Cavern's Dark Holes shows as a chain instead of nothing."""
        w = self.s.world
        pos = {center: (0, 0)}
        used = {(0, 0): center}
        self._vlinks = []                      # (from, to, "U"/"D"/"X")
        q = deque([(center, 0)])
        while q:
            room, depth = q.popleft()
            if depth >= self.radius:
                continue
            r = w.room(room)
            if not r:
                continue
            x, y = pos[room]
            for d, ex in r.exits.items():
                if ex.to not in w.rooms:
                    continue
                if ex.to in pos:
                    if d in ("U", "D") or ex.to[0] != room[0]:
                        self._vlinks.append((room, ex.to, d if d in ("U", "D") else "X"))
                    continue
                cell = None
                if d in VEC and ex.to[0] == room[0]:
                    dx, dy = VEC[d]
                    c = (x + dx, y + dy)
                    if c not in used:
                        cell = c
                elif d in self.VERT or ex.to[0] != room[0]:
                    for dx, dy in self.VERT.get(d, self.VERT["U"]):
                        c = (x + dx, y + dy)
                        if c not in used:
                            cell = c
                            break
                    if cell:
                        self._vlinks.append((room, ex.to, d if d in ("U", "D") else "X"))
                if cell is None:
                    continue
                pos[ex.to] = cell
                used[cell] = ex.to
                q.append((ex.to, depth + 1))
        return pos

    def redraw(self):
        self.delete("all")
        st = self.s.state
        W, H = self.winfo_width(), self.winfo_height()
        if not self.s.world.loaded:
            self.create_text(W / 2, H / 2, text="Import an MME database\n(File → Import MME database…)",
                             fill="#8a94a6", font=("Segoe UI", 11), justify="center")
            return
        me = st.room or (st.candidates[0] if st.candidates else None)
        ov = MapView.overlay() if MapView.overlay else None
        if self.scout and self.scout[1] != me and self.follow:
            self.scout = None                           # you moved: back to following you
        center = (ov or {}).get("center") or (self.scout[0] if self.scout else None) or me
        trail = set((ov or {}).get("trail") or [])
        start = (ov or {}).get("start")
        if not center:
            self.create_text(W / 2, H / 2, text="Location unknown — press Enter in the game to look",
                             fill="#8a94a6", font=("Segoe UI", 11))
            return
        self._center = center
        if self.grid_n:
            self.radius = max(3, self.grid_n // 2)
            self.CELL = max(6, min(60, int(min(W, H - 30) / self.grid_n)))
            self.BOX = max(4, int(self.CELL * 0.55))
        pos = self.layout(center)
        self._pos = pos
        cx, cy = W / 2, H / 2
        C, B = self.CELL, self.BOX
        path_rooms = set()
        if self.s.bot.walking and self.s.bot.path:
            path_rooms = {s.room for s in self.s.bot.path.steps if s.room}
        if self.highlight is not None:
            path_rooms = set(self.highlight)
        w = self.s.world
        # exits
        for room, (x, y) in pos.items():
            r = w.room(room)
            for d, ex in r.exits.items():
                if ex.to in pos and d in VEC:
                    x2, y2 = pos[ex.to]
                    if (x2 - x, y2 - y) == VEC[d]:
                        dash = (3, 3) if not ex.visible else None
                        col = "#e6c229" if ex.kind == "trap" else "#c98a3b" if ex.door else "#4a5568"
                        self.create_line(cx + x * C, cy + y * C, cx + x2 * C, cy + y2 * C,
                                         fill=col, width=2, dash=dash)
        # up / down / other-map links: dashed, with an arrow in the middle
        for a, b, kind in getattr(self, "_vlinks", []):
            if a in pos and b in pos:
                (x1, y1), (x2, y2) = pos[a], pos[b]
                X1, Y1, X2, Y2 = cx + x1 * C, cy + y1 * C, cx + x2 * C, cy + y2 * C
                self.create_line(X1, Y1, X2, Y2, fill="#7aa2d6", width=2, dash=(4, 2))
                if kind in ("U", "D"):
                    continue                     # the room itself shows ▲/▼
                mark = "⇢"
                self.create_text((X1 + X2) / 2, (Y1 + Y2) / 2, text=mark, fill="#cfe0ff",
                                 font=("Segoe UI", max(7, int(B * 0.6)), "bold"))
        # Record Path / Record Loop: the way walked so far, in red
        rr = getattr(self.s, "routerec", None)
        rec_rooms = list(rr.rooms) if rr is not None and rr.active else []
        for a_, b_ in zip(rec_rooms, rec_rooms[1:]):
            if a_ in pos and b_ in pos:
                (x1, y1), (x2, y2) = pos[a_], pos[b_]
                self.create_line(cx + x1 * C, cy + y1 * C, cx + x2 * C, cy + y2 * C, fill="#ff4d4d", width=3,
                                 arrow="last", arrowshape=(8, 9, 3))
        # rooms
        cands = set(st.candidates)
        for room, (x, y) in pos.items():
            r = w.room(room)
            px, py = cx + x * C, cy + y * C
            fill = "#2a3342"
            if room in path_rooms:
                fill = "#1f4f7a"
            if r.shop:
                fill = "#4b3b72"
            if r.lair:
                fill = "#8b2525"              # regen room (monsters respawn here)
            outline = "#6b7a90"
            trap = any(e.kind == "trap" for e in r.exits.values())
            if room in trail:
                fill = "#8a6d1a"                  # path builder trail
            if ov and room == center:
                fill, outline = "#ffd23f", "#fff4c2"      # the pen
            elif room == me:
                fill, outline = "#2fbf71", "#d6ffe6"
            elif room in cands:
                outline = "#2fbf71"
            if start and room == start and room != center:
                outline = "#5aa9ff"
            if self.scout and room == center and not ov:
                outline = "#ffd23f"                        # the room you're looking from
            if rec_rooms and room == rec_rooms[0]:
                outline = "#ff4d4d"                        # where the recording started
            if self.selected and room == self.selected:
                outline = "#36d6ff"                        # the room in the room panel
            self.create_rectangle(px - B / 2, py - B / 2, px + B / 2, py + B / 2,
                                  fill=fill, outline=outline, width=2 if room in (center, me, start) else 1,
                                  tags=("room", f"r{room[0]}_{room[1]}"))
            if trap:
                self.create_text(px, py, text="!", fill="#ffd23f", font=("Segoe UI", max(7, int(B * 0.8)), "bold"),
                                 tags=("room", f"r{room[0]}_{room[1]}"))
            # up / down: a clear arrow inside the room (cyan = up, orange = down), like MME
            ud = [k for k in ("U", "D") if k in r.exits]
            if ud:
                fs = max(8, int(B * (0.55 if len(ud) == 1 else 0.42)))
                for i, k in enumerate(ud):
                    dx = 0 if len(ud) == 1 else (-B / 4 if k == "U" else B / 4)
                    self.create_text(px + dx, py, text="▲" if k == "U" else "▼",
                                     fill="#5fe3ff" if k == "U" else "#ffad4a",
                                     font=("Segoe UI", fs, "bold"), tags=("room", f"r{room[0]}_{room[1]}"))
        # Edit loop: the marks on each room (NA no attack, DR don't rest, $ stash)
        bad = self.badges() if self.badges else {}
        for room, txt in bad.items():
            if room in pos and txt:
                x, y = pos[room]
                self.create_text(cx + x * C + B / 2 + 1, cy + y * C - B / 2 - 1, anchor="sw", text=txt,
                                 fill="#ffd23f", font=("Segoe UI", max(7, int(B * 0.5)), "bold"),
                                 tags=("room", f"r{room[0]}_{room[1]}"))
        # monsters in current room
        if st.view and st.view.monsters and st.room and center == me:
            n = len(st.view.monsters)
            self.create_text(cx, cy - B, text=f"{n}", fill="#ff6b6b", font=("Segoe UI", 9, "bold"))
        if rec_rooms:
            self.create_text(W - 10, 10, anchor="ne", fill="#ff4d4d", font=("Segoe UI", 10, "bold"), text=rr.label())
        r = w.room(center)
        tag = "  ·  PATH BUILDER" if ov else ("  ·  looking around (⌖ Me to come back)" if not self.follow else
                                                "  ·  scouting (moves back when you do)") if self.scout else ""
        if self.highlight is not None:
            tag = "  ·  editing the loop"
        self.create_text(10, 10, anchor="nw", fill="#ffd23f" if (ov or self.scout) else "#e0e6ef",
                         font=("Segoe UI", 10, "bold"), text=f"Map {center[0]}  Room {center[1]}  —  {r.name}{tag}")
        x0 = 10
        for sw, label in (("#2fbf71", "you"), ("#1f4f7a", "path"), ("#8b2525", "regen"), ("#4b3b72", "shop"),
                          ("!", "trap"), ("#c98a3b", "door"), ("┄", "hidden"), ("▲", "up"), ("▼", "down")):
            if sw.startswith("#"):
                self.create_rectangle(x0, H - 16, x0 + 9, H - 7, fill=sw, outline="")
                x0 += 12
            else:
                self.create_text(x0, H - 6, anchor="sw", text=sw, fill={"!": "#ffd23f", "▲": "#5fe3ff", "▼": "#ffad4a"}.get(sw, "#8a94a6"),
                                 font=("Segoe UI", 8, "bold"))
                x0 += 8 + 6 * len(sw)
            self.create_text(x0, H - 6, anchor="sw", fill="#8a94a6", font=("Segoe UI", 8), text=label)
            x0 += 8 + 6 * len(label)

    def _room_at(self, ex, ey):
        W, H = self.winfo_width(), self.winfo_height()
        C = self.CELL
        gx, gy = round((ex - W / 2) / C), round((ey - H / 2) / C)
        for room, p in self._pos.items():
            if p == (gx, gy):
                return room
        return None

    def _hover(self, e):
        room = self._room_at(e.x, e.y)
        self.delete("tip")
        if room:
            r = self.s.world.room(room)
            txt = f"{room[0]}/{room[1]} {r.name}"
            if r.lair:
                txt += "  · regen room"
                mobs = self._lair_mobs(r.lair)
                if mobs:
                    txt += f": {mobs}"
            traps = [f"{d.lower()} {e.etype.strip('()')}" for d, e in r.exits.items() if e.kind == "trap"]
            if traps:
                txt += "  · TRAP " + ", ".join(traps)
            self.create_text(e.x + 12, e.y + 12, anchor="nw", text=txt, fill="#ffffff",
                             font=("Segoe UI", 9), tags="tip")

    def _lair_mobs(self, lair: str) -> str:
        """'(Max 2): 802,832,...' -> 'max 2: orc, goblin…'"""
        import re
        m = re.match(r"\(Max (\d+)\):\s*([\d,]+)", lair or "")
        if not m:
            return ""
        names = []
        for n in m.group(2).split(","):
            rec = self.s.world.monsters.get(int(n)) if n.strip().isdigit() else None
            if rec and rec["name"] not in names:
                names.append(rec["name"])
        more = "…" if len(names) > 4 else ""
        return f"max {m.group(1)} — " + ", ".join(names[:4]) + more

    def _scout(self, e):
        """Right-click a room: centre the map there to look ahead; it snaps back when you move."""
        room = self._room_at(e.x, e.y)
        st = self.s.state
        me = st.room or (st.candidates[0] if st.candidates else None)
        if room and room != me:
            self.scout = (room, me)
        else:
            self.scout = None
        self.redraw()

    def _pan_key(self, e):
        """Number pad (8 n, 3 se, 0 d, . u …) or arrow keys: look one room that way on this map."""
        import sys
        from .macros import key_name
        arrows = {"Up": "N", "Down": "S", "Left": "W", "Right": "E"}
        d = arrows.get(e.keysym)
        if not d:
            win = sys.platform.startswith("win")
            name = key_name(e.keysym, e.keycode, e.state, win, extended=bool(e.state & 0x20000) if win else True)
            if name and name.startswith("Keypad "):
                d = {"8": "N", "2": "S", "4": "W", "6": "E", "7": "NW", "9": "NE", "1": "SW", "3": "SE",
                     "0": "U", ".": "D"}.get(name.split(" ", 1)[1])
        if not d:
            return None
        st = self.s.state
        me = st.room or (st.candidates[0] if st.candidates else None)
        cur = self.scout[0] if self.scout else me
        r = self.s.world.room(cur) if cur else None
        ex = r.exits.get(d) if r else None
        if ex and ex.to in self.s.world.rooms:
            self.scout = (ex.to, me)
            self.redraw()
        else:
            self.bell()
        return "break"

    def _click(self, e):
        if not self.on_click:
            return
        room = self._room_at(e.x, e.y)
        if room:
            self.selected = room
            self.on_click(room)
            self.redraw()

    def _dbl(self, e):
        room = self._room_at(e.x, e.y)
        if room and self.on_goto:
            self.on_goto(room)


def search(session, text: str, limit: int = 40) -> list:
    """[(label, (map, room))] for the map's search box: 'map/room', your Rooms.md places, monsters (where they
    spawn) and room names — places and exact names first."""
    import re
    w = session.world
    q = (text or "").strip().lower()
    if not q or not w.loaded:
        return []
    out, seen = [], set()

    def add(label, key):
        key = tuple(key)
        if key in w.rooms and key not in seen:
            seen.add(key)
            out.append((label, key))
    m = re.match(r"^(\d{1,3})\s*[/ ,]\s*(\d{1,5})$", q)
    if m:
        k = (int(m.group(1)), int(m.group(2)))
        r = w.room(k)
        if r:
            add(f"{k[0]}/{k[1]} {r.name}", k)
    mn = re.match(r"^(?:room\s*)?(\d{1,5})$", q)
    if mn:
        # just the room number: this map's first, then the same number on the others
        num = int(mn.group(1))
        st = session.state
        here = st.room or (st.candidates[0] if st.candidates else None)
        maps = sorted({k[0] for k in w.rooms if k[1] == num}, key=lambda mp_: (not here or mp_ != here[0], mp_))
        for mp_ in maps:
            add(f"{mp_}/{num} {w.room((mp_, num)).name}", (mp_, num))
    try:
        places = session.known_rooms()
    except Exception:
        places = []
    for _g, n, k in places:
        if q in n.lower():
            add(f"{n} — {k[0]}/{k[1]}", k)
    for mon in w.monsters.values():
        if q in (mon.get("name") or "").lower():
            for k in (mon.get("spawn_rooms") or [])[:3]:
                r = w.room(tuple(k))
                add(f"{mon['name']} (spawns) — {r.name if r else ''} {k[0]}/{k[1]}", k)
        if len(out) >= limit:
            break
    names = sorted(((r.name, k) for k, r in w.rooms.items() if q in r.name.lower()),
                   key=lambda x: (x[0].lower() != q, not x[0].lower().startswith(q), x[0], x[1]))
    for n, k in names:
        if len(out) >= limit:
            break
        add(f"{n} — {k[0]}/{k[1]}", k)
    return out[:limit]


class MapSearch:
    """A search box for a map: type and press Enter, pick a hit, and the map centres there (outlined in yellow).
    Double-click the room to walk there."""

    def __init__(self, bar, mapview, width=24):
        from tkinter import ttk
        self.m = mapview
        self.hits = []
        self.var = tk.StringVar()
        # (a plain label: the 🔍 alone was easy to miss — Dan, 2026-11-01, asked for a room search that was there)
        ttk.Label(bar, text="Find room").pack(side="left")
        MapSearch._n = getattr(MapSearch, "_n", 0) + 1
        self._style = f"MapSearch{MapSearch._n}.TCombobox"
        self.cb = ttk.Combobox(bar, textvariable=self.var, width=width, style=self._style)
        self.cb.pack(side="left", padx=(2, 6))
        self.cb.bind("<Return>", self._find)
        self.cb.bind("<<ComboboxSelected>>", self._pick)
        self.shown = None
        self.go = ttk.Button(bar, text="Go to", width=6, command=self._go, state="disabled")
        self.go.pack(side="left", padx=(0, 6))

    def _find(self, e=None):
        self.hits = search(self.m.s, self.var.get())
        if not self.hits:
            self.cb.configure(values=["(nothing found)"])
            self.m.bell()
            return "break"
        self.cb.configure(values=[h[0] for h in self.hits])
        self._widen()
        if len(self.hits) == 1:
            self.show(self.hits[0][1])
        else:
            self.cb.after(10, self._post)
        return "break"

    def _widen(self):
        """The box stays its size; the list drops down as wide as the longest hit (Dan: "Rugged Shoreline,
        Tidepool —" was cut off before the room number)."""
        from tkinter import ttk, font as tkfont
        try:
            f = tkfont.nametofont(str(self.cb.cget("font")) or "TkDefaultFont")
        except Exception:
            f = tkfont.nametofont("TkDefaultFont")
        need = max((f.measure(h[0]) for h in self.hits), default=0) + 40      # + scrollbar and padding
        have = self.cb.winfo_width() or 1
        top = self.cb.winfo_toplevel()
        room = max(0, top.winfo_rootx() + top.winfo_width() - self.cb.winfo_rootx() - have - 8)
        extra = max(0, min(need - have, max(room, 300)))
        ttk.Style().configure(self._style, postoffset=(0, 0, extra, 0))

    def _post(self):
        try:
            self.cb.tk.call("ttk::combobox::Post", self.cb)      # open the list of hits
        except Exception:
            self.cb.event_generate("<Down>")

    def _pick(self, e=None):
        lab = self.var.get()
        hit = next((k for l, k in self.hits if l == lab), None)
        if hit:
            self.show(hit)

    def _go(self):
        """Walk to the room the search found (same as double-clicking it)."""
        if self.shown and self.m.on_goto:
            self.m.on_goto(self.shown)

    def show(self, key):
        self.shown = tuple(key)
        try:
            self.go.configure(state="normal")
        except tk.TclError:
            pass
        if self.m.on_click:
            self.m.selected = self.shown
            self.m.on_click(self.shown)          # the room panel shows it too
        st = self.m.s.state
        me = st.room or (st.candidates[0] if st.candidates else None)
        self.m.scout = (tuple(key), me)
        self.m.redraw()
