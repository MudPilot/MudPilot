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
    loaded copy of the same loop (the one being walked)."""
    rooms = dict(loop_rooms(mp))
    flags = [s.flags for s in mp.steps]
    for key, want in marks.items():
        for i in rooms.get(key, ()):
            for name, on in want.items():
                if name not in STEPF:
                    continue                         # RUNTHRU lives in the settings, not the file
                bit = STEPF[name]
                flags[i] = (flags[i] | bit) if on else (flags[i] & ~bit)
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


def badge(marks: dict, stash: bool) -> str:
    return " ".join(t for t, on in (("NA", marks.get("NOATTACK")), ("DR", marks.get("DONTREST")),
                                    ("RT", marks.get("RUNTHRU")), ("$", stash)) if on)


def edit_loop_dialog(app, mp):
    """MME-style loop editor (0.8.210, Dan): the loop on a map — walk round it (arrow keys / number pad, or Prev /
    Next room), click a room, and tick No attack / Don't rest / Stash room here. The list on the right is the same
    rooms in loop order."""
    import tkinter as tk
    from tkinter import ttk, messagebox
    from .extras import room_text
    from .mapview import MapView
    s = app.s
    w = s.world
    cfg = s.settings
    rows = loop_rooms(mp)
    state = {}
    for key, idx in rows:
        state[key] = {f: all(mp.steps[i].flag(f) for i in idx) for f, _l in EDIT_FLAGS}
    lk = loop_key(mp)
    stash = {"room": room_text((cfg.loop_stash or {}).get(lk, "")) or None}
    rt_old = {room_text(x) for x in ((cfg.loop_runthru or {}).get(lk) or [])} - {None}
    for key in state:
        state[key]["RUNTHRU"] = key in rt_old
    on_loop = [k for k, _i in rows if isinstance(k, tuple)]
    d = tk.Toplevel(app.root)
    d.title(f"Edit loop: {mp.title} - MudPilot")
    d.transient(app.root)
    try:
        d.configure(background="#151a21")
    except tk.TclError:
        pass
    d.geometry("1180x660")
    fr = ttk.Frame(d, padding=10)
    fr.pack(fill="both", expand=True)
    ttk.Label(fr, text="Walk round the loop on the map (arrow keys / number pad, or Prev / Next room) or click a "
                       "room, then tick what goes there. No attack: walk through without fighting, even when hit "
                       "(pile mobs up for an area spell). Don't rest: never stop to rest here. Run through: wait for a "
                       "combat round to go off, then cross the room before the next one (no fighting, no stopping). "
                       "Stash room: this loop's stash. Blue rooms are the loop; NA / DR / RT / $ show the marks.",
              style="Muted.TLabel", wraplength=1140, justify="left").pack(anchor="w", pady=(0, 6))
    pw = ttk.PanedWindow(fr, orient="horizontal")
    pw.pack(fill="both", expand=True)
    left = ttk.Frame(pw)
    right = ttk.Frame(pw)
    pw.add(left, weight=3)
    pw.add(right, weight=2)
    mv = MapView(left, s, follow=False, width=640, height=470)
    mv.highlight = set(on_loop)
    mv.badges = lambda: {k: badge(state[k], k == stash["room"]) for k in on_loop}
    mv.pack(fill="both", expand=True)
    sel_lbl = ttk.Label(left, text="", font=("Segoe UI", 10, "bold"))
    sel_lbl.pack(anchor="w", pady=(6, 2))
    tick = ttk.Frame(left)
    tick.pack(fill="x")
    v_na, v_dr, v_rt, v_st = tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar(), tk.BooleanVar()
    cur = {"key": None}

    cols = ("n", "room", "name", "NOATTACK", "DONTREST", "RUNTHRU", "STASH")
    tv = ttk.Treeview(right, columns=cols, show="headings", height=20, selectmode="browse")
    for c, t, wd, anc in (("n", "Step", 42, "e"), ("room", "Room", 70, "w"), ("name", "Name", 210, "w"),
                          ("NOATTACK", "No attack", 70, "center"), ("DONTREST", "Don't rest", 70, "center"),
                          ("RUNTHRU", "Run through", 78, "center"), ("STASH", "Stash", 50, "center")):
        tv.heading(c, text=t)
        tv.column(c, width=wd, anchor=anc)
    sb = ttk.Scrollbar(right, orient="vertical", command=tv.yview)
    tv.configure(yscrollcommand=sb.set)
    tv.pack(side="left", fill="both", expand=True)
    sb.pack(side="left", fill="y")
    iid_key, key_iid = {}, {}

    def box(on):
        return "☑" if on else "☐"

    def vals(key, idx):
        if isinstance(key, tuple):
            r = w.room(key) if w else None
            room, name = f"{key[0]}/{key[1]}", (r.name if r else "?")
        else:
            room, name = "?", f"(not matched to a room: {key})"
        return (idx[0] + 1, room, name, box(state[key]["NOATTACK"]), box(state[key]["DONTREST"]),
                box(state[key]["RUNTHRU"]), box(key == stash["room"]))

    for n, (key, idx) in enumerate(rows):
        iid = str(n)
        iid_key[iid], key_iid[key] = key, iid
        tv.insert("", "end", iid=iid, values=vals(key, idx))

    def refresh():
        for n, (key, idx) in enumerate(rows):
            tv.item(str(n), values=vals(key, idx))
        k = cur["key"]
        on = k in state
        v_na.set(bool(on and state[k]["NOATTACK"]))
        v_dr.set(bool(on and state[k]["DONTREST"]))
        v_rt.set(bool(on and state[k]["RUNTHRU"]))
        v_st.set(bool(on and k == stash["room"]))
        for cb in (c_na, c_dr, c_rt, c_st):
            cb.state(["!disabled"] if on else ["disabled"])
        if k and isinstance(k, tuple):
            r = w.room(k)
            sel_lbl.configure(text=f"{k[0]}/{k[1]}  {r.name if r else '?'}" + ("" if on else "  (not on this loop)"))
        mv.redraw()

    def select(key, from_map=False, see=True):
        cur["key"] = key
        if isinstance(key, tuple):
            mv.selected = key
            if not from_map:
                st = s.state
                mv.scout = (key, st.room or (st.candidates[0] if st.candidates else None))
        iid = key_iid.get(key)
        if iid and tuple(tv.selection()) != (iid,):
            tv.selection_set(iid)
            if see:
                tv.see(iid)
        refresh()

    def toggle(flag):
        k = cur["key"]
        if k not in state:
            return
        if flag == "STASH":
            stash["room"] = None if stash["room"] == k else k
        else:
            state[k][flag] = not state[k][flag]
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
        if sel and iid_key.get(sel[0]) != cur["key"]:
            select(iid_key[sel[0]], see=False)
    tv.bind("<<TreeviewSelect>>", on_tv)

    def tv_click(e):
        iid, col = tv.identify_row(e.y), tv.identify_column(e.x)
        if not iid or not col:
            return
        j = int(col[1:]) - 1
        if j >= 3:
            select(iid_key[iid], see=False)
            toggle(cols[j])
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
        if not apply(mp, state, others=[getattr(bot, "path", None)] + list(s.paths)):
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
        n_na = sum(1 for v in state.values() if v["NOATTACK"])
        n_dr = sum(1 for v in state.values() if v["DONTREST"])
        n_rt = sum(1 for v in state.values() if v["RUNTHRU"])
        st_txt = f"{stash['room'][0]}/{stash['room'][1]}" if stash["room"] else "the default"
        app.add_log(f"Saved '{mp.title}': {n_na} no-attack room(s), {n_dr} don't-rest room(s), {n_rt} run-through "
                    f"room(s), stash {st_txt}")
        d.destroy()
    b = ttk.Frame(fr)
    b.pack(fill="x", pady=(8, 0))
    ttk.Button(b, text="Find my room", command=mine).pack(side="left")
    ttk.Button(b, text="Save", style="Accent.TButton", command=save).pack(side="right")
    ttk.Button(b, text="Cancel", command=d.destroy).pack(side="right", padx=6)
    here = tuple(s.state.room) if s.state.room else None
    start = here if here in state else (stash["room"] or (on_loop[0] if on_loop else None))
    d.after(50, lambda: start and select(start))
    mv.focus_set()
    return d
