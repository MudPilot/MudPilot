"""Edit loop (0.8.206, Dan): mark rooms on a saved loop/path "No attack" or "Don't rest".

These are MegaMUD's own per-step flags (STEPF NOATTACK / DONTREST), which the walker already obeys. Marking a
room marks every step that starts in it. Only the flags field of those step lines is rewritten, so the file stays
as MegaMUD wrote it otherwise (and MegaMUD still reads it)."""
from __future__ import annotations

import os
import re

from .megamud_files import STEPF

EDIT_FLAGS = (("NOATTACK", "No attack"), ("DONTREST", "Don't rest"))
_STEP_RE = re.compile(r"^([0-9A-Fa-f]{8}):([0-9A-Fa-f]+):(.*)$")


def loop_rooms(mp):
    """[(key, step indexes)] in loop order, one per room (a room walked through twice is one row)."""
    out, seen = [], {}
    for i, s in enumerate(mp.steps):
        key = tuple(s.room) if getattr(s, "room", None) else s.hash
        if key in seen:
            out[seen[key]][1].append(i)
        else:
            seen[key] = len(out)
            out.append((key, [i]))
    return out


def loop_visits(mp) -> dict:
    """{room key: [[step indexes], …]} — each time the loop passes through a room is one visit (a run of steps that
    start in it back to back), in loop order. 0.8.227 (Dan): a room walked twice can be No attack on one pass only."""
    out = {}
    prev = object()
    for i, s in enumerate(mp.steps):
        key = tuple(s.room) if getattr(s, "room", None) else s.hash
        if key == prev and key in out:
            out[key][-1].append(i)
        else:
            out.setdefault(key, []).append([i])
        prev = key
    return out


def visit_dirs(mp, idx) -> tuple:
    """('W', 'N'): how a visit (its step indexes) comes in and goes out. In = the move before it (the loop's last step
    for the first one), out = its last step's move; raw commands come back as they are."""
    def mv(s):
        return (s.move or "").strip() if s is not None else ""
    n = len(mp.steps)
    before = mp.steps[idx[0] - 1] if n and (idx[0] > 0 or n > 1) else None
    return mv(before), mv(mp.steps[idx[-1]])


ORD = {1: "1st", 2: "2nd", 3: "3rd"}


def nth(n) -> str:
    return ORD.get(n, f"{n}th")


def write_flags(mp, flags: list[int]) -> bool:
    """Put new step flags into mp's file (flags[i] for step i) and into mp. False if the file can't be matched."""
    fn = getattr(mp, "filename", "")
    if not fn or not os.path.exists(fn) or len(flags) != len(mp.steps):
        return False
    with open(fn, encoding="latin-1", newline="") as f:
        lines = f.read().split("\n")
    hits = []
    for n, ln in enumerate(lines):
        m = _STEP_RE.match(ln.rstrip("\r").strip())
        if m and ln.count(":") >= 2:
            hits.append(n)
    # the header line (start:end:count:...) also starts with 8 hex digits — the steps are the last len(steps) hits
    if len(hits) < len(mp.steps):
        return False
    hits = hits[-len(mp.steps):]
    for i, n in enumerate(hits):
        ln = lines[n]
        cr = "\r" if ln.endswith("\r") else ""
        h, old, rest = ln.rstrip("\r").split(":", 2)
        if h.strip().upper() != mp.steps[i].hash.upper():
            return False                       # the file changed under us — don't write the wrong lines
        lines[n] = f"{h}:{flags[i]:0{max(4, len(old))}X}:{rest}{cr}"
    with open(fn, "w", encoding="latin-1", newline="") as f:
        f.write("\n".join(lines))
    for s, fl in zip(mp.steps, flags):
        s.flags = fl
    return True


def apply(mp, marks: dict, others=()) -> bool:
    """marks: {room key: {"NOATTACK": bool, "DONTREST": bool}}. Writes the file; copies the flags onto any other
    loaded copy of the same loop (the one being walked). marks[key]["visits"] = [{"NOATTACK": …}, …] sets each pass
    through the room on its own (loop_visits order); it wins over room-wide NOATTACK / DONTREST."""
    rooms = dict(loop_rooms(mp))
    visits = loop_visits(mp)
    flags = [s.flags for s in mp.steps]

    def put(idx, want):
        for i in idx:
            for name, on in want.items():
                if name not in STEPF:
                    continue                         # RUNTHRU lives in the settings, not the file
                bit = STEPF[name]
                flags[i] = (flags[i] | bit) if on else (flags[i] & ~bit)
    for key, want in marks.items():
        per = want.get("visits")
        room_wide = {k: v for k, v in want.items() if k != "visits"}
        if per:
            room_wide = {k: v for k, v in room_wide.items() if k not in ("NOATTACK", "DONTREST")}
        put(rooms.get(key, ()), room_wide)
        for idx, vw in zip(visits.get(key, ()), per or ()):
            put(idx, vw)
    if not write_flags(mp, flags):
        return False
    for o in others:
        if o is not None and o is not mp and getattr(o, "filename", None) == mp.filename \
                and len(o.steps) == len(flags):
            for s, fl in zip(o.steps, flags):
                s.flags = fl
    return True


def loop_key(mp) -> str:
    """The loop's name in Settings.loop_stash (same as Extras.loop_key)."""
    return (os.path.basename(mp.filename) if getattr(mp, "filename", None) else mp.title).lower()


OPP = {"N": "S", "S": "N", "E": "W", "W": "E", "NE": "SW", "SW": "NE", "NW": "SE", "SE": "NW", "U": "below",
       "D": "above"}


def visit_text(mp, idx, n) -> str:
    """'1st time through — in from W, out N' (a raw command shows as it is: "in by 'go path'")."""
    a, b = visit_dirs(mp, idx)
    inn = f"in from {OPP[a.upper()]}" if a.upper() in OPP else (f"in by '{a}'" if a else "start")
    out = f"out {b.upper()}" if b.upper() in OPP else (f"out by '{b}'" if b else "end")
    return f"{nth(n)} time through — {inn}, {out}"


def badge(marks: dict, stash: bool, visits=None) -> str:
    """'NA DR $' — with visits (per-pass flags), a mark on only some passes shows which: 'NA 2/2', 'NA 1,3/3'."""
    def one(tag, flag):
        if visits and len(visits) > 1:
            on = [n for n, v in enumerate(visits, 1) if v.get(flag)]
            if not on:
                return None
            return tag if len(on) == len(visits) else f"{tag} {','.join(map(str, on))}/{len(visits)}"
        if visits:
            return tag if visits[0].get(flag) else None
        return tag if marks.get(flag) else None
    parts = [one("NA", "NOATTACK"), one("DR", "DONTREST"), "RT" if marks.get("RUNTHRU") else None,
             "$" if stash else None]
    return " ".join(p for p in parts if p)


def edit_loop_dialog(app, mp):
    """MME-style loop editor (0.8.210, Dan): the loop on a map — walk round it (arrow keys / number pad, or Prev /
    Next room), click a room, and tick No attack / Don't rest / Stash room here. The list on the right is the same
    rooms in loop order. 0.8.227: a room the loop passes through more than once gets a line per pass (No attack /
    Don't rest on that pass only), and the pass picked shows on the map as arrows in and out."""
    import tkinter as tk
    from tkinter import ttk, messagebox
    from .extras import room_text
    from .mapview import MapView
    s = app.s
    w = s.world
    cfg = s.settings
    rows = loop_rooms(mp)
    visits = loop_visits(mp)
    vstate = {key: [{f: all(mp.steps[i].flag(f) for i in idx) for f, _l in EDIT_FLAGS} for idx in visits[key]]
              for key, _i in rows}
    state = {key: {} for key, _i in rows}               # room-wide: RUNTHRU (NOATTACK / DONTREST live in vstate)
    lk = loop_key(mp)
    stash = {"room": room_text((cfg.loop_stash or {}).get(lk, "")) or None}
    rt_old = {room_text(x) for x in ((cfg.loop_runthru or {}).get(lk) or [])} - {None}
    for key in state:
        state[key]["RUNTHRU"] = key in rt_old
    on_loop = [k for k, _i in rows if isinstance(k, tuple)]

    def all_on(key, flag):
        return all(v[flag] for v in vstate[key])

    def any_on(key, flag):
        return any(v[flag] for v in vstate[key])
    d = tk.Toplevel(app.root)
    d.title(f"Edit loop: {mp.title} - MudPilot")
    d.transient(app.root)
    try:
        d.configure(background="#151a21")
    except tk.TclError:
        pass
    d.geometry("1180x740")
    fr = ttk.Frame(d, padding=10)
    fr.pack(fill="both", expand=True)
    ttk.Label(fr, text="Walk round the loop on the map (arrow keys / number pad, or Prev / Next room) or click a "
                       "room, then tick what goes there. No attack: walk through without fighting, even when hit "
                       "(pile mobs up for an area spell). Don't rest: never stop to rest here. A room the loop passes "
                       "through more than once has a line for each time through, so you can mark just one pass — "
                       "the arrows on the map show which way that pass comes in and goes out. Run through: wait for "
                       "a combat round to go off, then cross the room before the next one (no fighting, no stopping). "
                       "Stash room: this loop's stash. Blue rooms are the loop; NA / DR / RT / $ show the marks "
                       "(NA 2/2 = only the 2nd time through).",
              style="Muted.TLabel", wraplength=1140, justify="left").pack(anchor="w", pady=(0, 6))
    b = ttk.Frame(fr)                            # the buttons first, so the visit lines never push them off
    b.pack(side="bottom", fill="x", pady=(8, 0))
    pw = ttk.PanedWindow(fr, orient="horizontal")
    pw.pack(fill="both", expand=True)
    left = ttk.Frame(pw)
    right = ttk.Frame(pw)
    pw.add(left, weight=3)
    pw.add(right, weight=2)
    mv = MapView(left, s, follow=False, width=640, height=440)
    mv.highlight = set(on_loop)
    mv.badges = lambda: {k: badge(state[k], k == stash["room"], vstate[k]) for k in on_loop}
    mv.pack(fill="both", expand=True)
    sel_lbl = ttk.Label(left, text="", font=("Segoe UI", 10, "bold"))
    sel_lbl.pack(anchor="w", pady=(6, 2))
    tick = ttk.Frame(left)
    tick.pack(fill="x")
    vis_fr = ttk.Frame(left)                    # one line per time through (rooms passed more than once)
    vis_fr.pack(fill="x")
    v_na, v_dr, v_rt, v_st = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
    cur = {"key": None, "v": 0, "built": None}

    # the list: one row per room, or one per time through for a room passed more than once
    lrows = []                                   # (key, visit number or None, step indexes)
    for key, idx in rows:
        vs = visits.get(key) or [idx]
        if len(vs) > 1:
            lrows.extend((key, n, vi) for n, vi in enumerate(vs, 1))
        else:
            lrows.append((key, None, idx))
    lrows.sort(key=lambda r: r[2][0])
    cols = ("n", "room", "name", "NOATTACK", "DONTREST", "RUNTHRU", "STASH")
    tv = ttk.Treeview(right, columns=cols, show="headings", height=20, selectmode="browse")
    for c, t, wd, anc in (("n", "Step", 42, "e"), ("room", "Room", 86, "w"), ("name", "Name", 180, "w"),
                          ("NOATTACK", "No attack", 70, "center"), ("DONTREST", "Don't rest", 70, "center"),
                          ("RUNTHRU", "Run through", 78, "center"), ("STASH", "Stash", 50, "center")):
        tv.heading(c, text=t)
        tv.column(c, width=wd, anchor=anc)
    sb = ttk.Scrollbar(right, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb.set)
    tv.pack(side="left", fill="both", expand=True)
    sb.pack(side="left", fill="y")
    iid_row, row_iid = {}, {}

    def box(on):
        return "☑" if on else "☐"

    def flag_of(key, vn, f):
        return vstate[key][vn - 1][f] if vn else all_on(key, f)

    def vals(key, vn, idx):
        if isinstance(key, tuple):
            r = w.room(key) if w else None
            room, name = f"{key[0]}/{key[1]}", (r.name if r else "?")
        else:
            room, name = "?", f"(not matched to a room: {key})"
        if vn:
            room += f" ({nth(vn)})"
        return (idx[0] + 1, room, name, box(flag_of(key, vn, "NOATTACK")), box(flag_of(key, vn, "DONTREST")),
                box(state[key]["RUNTHRU"]), box(key == stash["room"]))

    for n, (key, vn, idx) in enumerate(lrows):
        iid = str(n)
        iid_row[iid], row_iid[(key, vn)] = (key, vn), iid
        tv.insert("", "end", iid=iid, values=vals(key, vn, idx))

    vis_vars = []        # [(No attack var, Don't rest var, label)] for the room in the panel

    def build_visits(k):
        """The per-pass lines for room k (nothing for a room the loop passes once)."""
        if cur["built"] == k:
            return
        cur["built"] = k
        for c in vis_fr.winfo_children():
            c.destroy()
        vis_vars.clear()
        vs = visits.get(k) or []
        if k not in vstate or len(vs) < 2:
            return
        ttk.Label(vis_fr, text="Each time through (the boxes above set them all):",
                  style="Muted.TLabel").grid(row=0, column=0, columnspan=3, sticky="w", pady=(4, 0))
        for n, idx in enumerate(vs, 1):
            vna, vdr = tk.BooleanVar(), tk.BooleanVar()
            lb = ttk.Label(vis_fr, text=visit_text(mp, idx, n) + f"  (step {idx[0] + 1})", cursor="hand2")
            lb.grid(row=n, column=0, sticky="w", padx=(12, 14))
            lb.bind("<Button-1>", lambda e, n=n: select(cur["key"], n))
            vis_vars.append((vna, vdr, lb))
            ttk.Checkbutton(vis_fr, text="No attack", variable=vna,
                            command=lambda n=n: toggle("NOATTACK", n)).grid(row=n, column=1, sticky="w", padx=(0, 10))
            ttk.Checkbutton(vis_fr, text="Don't rest", variable=vdr,
                            command=lambda n=n: toggle("DONTREST", n)).grid(row=n, column=2, sticky="w")

    def arrows(k, vn):
        """In and out arrows for pass vn (or the only pass) through room k."""
        vs = visits.get(k) or []
        if not isinstance(k, tuple) or not vs:
            return []
        idx = vs[(vn or 1) - 1]
        n = len(mp.steps)
        out = []
        before = mp.steps[idx[0] - 1] if n > 1 else None
        if before is not None and before.room and tuple(before.room) != k:
            out.append((tuple(before.room), k))
        last = mp.steps[idx[-1]]
        nxt = last.dest or (mp.steps[(idx[-1] + 1) % n].room if n > 1 else None)
        if nxt and tuple(nxt) != k:
            out.append((k, tuple(nxt)))
        return out

    def refresh():
        for n, (key, vn, idx) in enumerate(lrows):
            tv.item(str(n), values=vals(key, vn, idx))
        k = cur["key"]
        on = k in state
        build_visits(k)
        for var, cb, f in ((v_na, c_na, "NOATTACK"), (v_dr, c_dr, "DONTREST")):
            a = bool(on and all_on(k, f))
            var.set(a)
            cb.state(["alternate"] if (on and not a and any_on(k, f)) else ["!alternate"])
        v_rt.set(bool(on and state[k]["RUNTHRU"]))
        v_st.set(bool(on and k == stash["room"]))
        for cb in (c_na, c_dr, c_rt, c_st):
            cb.state(["!disabled"] if on else ["disabled"])
        if on:
            for n, ((vna, vdr, lb), v) in enumerate(zip(vis_vars, vstate[k]), 1):
                vna.set(v["NOATTACK"])
                vdr.set(v["DONTREST"])
                lb.configure(font=("Segoe UI", 9, "bold" if n == cur["v"] else "normal"))
        if k and isinstance(k, tuple):
            r = w.room(k)
            nv = len(visits.get(k) or [])
            sel_lbl.configure(text=f"{k[0]}/{k[1]}  {r.name if r else '?'}" + ("" if on else "  (not on this loop)")
                              + (f"  —  the loop passes through {nv} times" if on and nv > 1 else ""))
        mv.visit_arrows = arrows(k, cur["v"]) if on else []
        mv.redraw()

    def select(key, vn=None, from_map=False, see=True):
        if key != cur["key"]:
            cur["v"] = 0
        cur["key"] = key
        if len(visits.get(key) or []) < 2:
            cur["v"] = 0
        elif vn:
            cur["v"] = vn
        elif not cur["v"]:
            cur["v"] = 1
        if isinstance(key, tuple):
            mv.selected = key
            if not from_map:
                st = s.state
                mv.scout = (key, st.room or (st.candidates[0] if st.candidates else None))
        iid = row_iid.get((key, cur["v"] or None))
        if iid and tuple(tv.selection()) != (iid,):
            tv.selection_set(iid)
            if see:
                tv.see(iid)
        refresh()

    def toggle(flag, vn=None):
        k = cur["key"]
        if k not in state:
            return
        if flag == "STASH":
            stash["room"] = None if stash["room"] == k else k
        elif flag == "RUNTHRU":
            state[k][flag] = not state[k][flag]
        elif vn:
            vstate[k][vn - 1][flag] = not vstate[k][vn - 1][flag]
        else:
            want = not all_on(k, flag)
            for v in vstate[k]:
                v[flag] = want
        if vn:
            select(k, vn, see=False)
        else:
            refresh()

    c_na = ttk.Checkbutton(tick, text="No attack here", variable=v_na, command=lambda: toggle("NOATTACK"))
    c_dr = ttk.Checkbutton(tick, text="Don't rest here", variable=v_dr, command=lambda: toggle("DONTREST"))
    c_rt = ttk.Checkbutton(tick, text="Run through (time the round)", variable=v_rt,
                           command=lambda: toggle("RUNTHRU"))
    c_st = ttk.Checkbutton(tick, text="Stash room here", variable=v_st, command=lambda: toggle("STASH"))
    for cb in (c_na, c_dr, c_rt, c_st):
        cb.pack(side="left", padx=(0, 14))

    def step(dn):
        keys = [k for k, _i in rows]
        k = cur["key"]
        i = keys.index(k) if k in keys else -1
        select(keys[(i + dn) % len(keys)])

    nav = ttk.Frame(left)
    nav.pack(fill="x", pady=(4, 0))
    ttk.Button(nav, text="◀ Prev room", command=lambda: step(-1)).pack(side="left")
    ttk.Button(nav, text="Next room ▶", command=lambda: step(1)).pack(side="left", padx=6)

    def on_tv(e=None):
        sel = tv.selection()
        if sel and iid_row.get(sel[0]) != (cur["key"], cur["v"] or None):
            key, vn = iid_row[sel[0]]
            select(key, vn, see=False)
    tv.bind("<<TreeviewSelect>>", on_tv)

    def tv_click(e):
        iid, col = tv.identify_row(e.y), tv.identify_column(e.x)
        if not iid or not col:
            return
        j = int(col[1:]) - 1
        if j >= 3:
            key, vn = iid_row[iid]
            select(key, vn, see=False)
            toggle(cols[j], vn if cols[j] in ("NOATTACK", "DONTREST") else None)
            return "break"
    tv.bind("<Button-1>", tv_click)

    mv.on_click = lambda room: select(room, from_map=True)

    def after_pan(e):
        d.after_idle(lambda: mv.scout and mv.scout[0] != cur["key"] and select(mv.scout[0], from_map=True))
    mv.bind("<Key>", after_pan, add="+")

    def mine():
        here = s.state.room
        k = tuple(here) if here else None
        if k in state:
            select(k)
            return
        messagebox.showinfo("Edit loop", "You aren't standing on this loop.", parent=d)

    def save():
        bot = getattr(s, "bot", None)
        marks = {k: {"RUNTHRU": state[k]["RUNTHRU"], "visits": vstate[k]} for k in state}
        if not apply(mp, marks, others=[getattr(bot, "path", None)] + list(s.paths)):
            messagebox.showinfo("Edit loop", f"Couldn't rewrite {mp.filename or 'that file'} (it may have changed "
                                             f"on disk — reload paths and try again).", parent=d)
            return
        rt_new = {k for k, v in state.items() if v.get("RUNTHRU") and isinstance(k, tuple)}
        if rt_new != rt_old:
            lr = dict(cfg.loop_runthru or {})
            if rt_new:
                lr[lk] = [f"{k[0]}/{k[1]}" for k in sorted(rt_new)]
            else:
                lr.pop(lk, None)
            cfg.loop_runthru = lr
            cfg.save()
        ls = dict(cfg.loop_stash or {})
        old = room_text(ls.get(lk, "")) or None
        if stash["room"] != old:
            if stash["room"]:
                ls[lk] = f"{stash['room'][0]}/{stash['room'][1]}"
            else:
                ls.pop(lk, None)
            cfg.loop_stash = ls
            cfg.save()
            try:
                app._stash_label()
            except Exception:
                pass
        n_na = sum(1 for k in state if any_on(k, "NOATTACK"))
        n_dr = sum(1 for k in state if any_on(k, "DONTREST"))
        some = sum(1 for k in state for f in ("NOATTACK", "DONTREST") if any_on(k, f) and not all_on(k, f))
        n_rt = sum(1 for v in state.values() if v["RUNTHRU"])
        st_txt = f"{stash['room'][0]}/{stash['room'][1]}" if stash["room"] else "the default"
        app.add_log(f"Saved '{mp.title}': {n_na} no-attack room(s), {n_dr} don't-rest room(s), {n_rt} run-through "
                    f"room(s), stash {st_txt}" + (f" ({some} mark(s) on only some passes through a room)"
                                                   if some else ""))
        d.destroy()
    ttk.Button(b, text="Find my room", command=mine).pack(side="left")
    ttk.Button(b, text="Save", style="Accent.TButton", command=save).pack(side="right")
    ttk.Button(b, text="Cancel", command=d.destroy).pack(side="right", padx=6)
    here = tuple(s.state.room) if s.state.room else None
    start = here if here in state else (stash["room"] or (on_loop[0] if on_loop else None))
    d.after(50, lambda: start and select(start))
    mv.focus_set()
    return d
