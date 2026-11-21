"""Which area folder a path or loop you make goes in.

MegaMUD files carry their folder in the header ('[FFFF:Terra Fuego:Beach]'); the Loops picker groups by it. A loop
built or recorded in MudPilot used to get "MudPilot" — Dan's treasure-digging loop in Tierra del Fuego landed there
instead of next to that area's other loops (2026-10-29). Now: the folder the paths you already have use around the
start room (the same name, spelled the way your MegaMUD files spell it), else your Rooms.md group for it; nothing
nearby → None, and you're asked."""
from __future__ import annotations

import os
from collections import Counter, deque

GENERIC = {"", "mudpilot", "other", "from paths", "my places", "loops"}


def area_name(world, key) -> str:
    r = world.room(tuple(key)) if key else None
    return (r.name.split(",")[0].strip() if r else "") or ""


def _index(session) -> dict:
    """{room: Counter(folder)} from your paths (every room they pass) and Rooms.md."""
    idx: dict = {}
    for mp in getattr(session, "paths", None) or []:
        g = (mp.start_group or "").strip()
        if g.lower() in GENERIC:
            continue
        for st in mp.steps or []:
            for k in (st.room, st.dest):
                if k:
                    idx.setdefault(tuple(k), Counter())[g] += 1
    try:
        for g, _n, k in session.known_rooms():
            if (g or "").strip().lower() not in GENERIC:
                idx.setdefault(tuple(k), Counter())[g.strip()] += 3
    except Exception:
        pass
    return idx


def folders(session) -> list:
    """Every folder your paths and loops are in (for the 'which folder?' box)."""
    seen = Counter((mp.start_group or "").strip() for mp in getattr(session, "paths", None) or [])
    return sorted((g for g in seen if g), key=str.lower)


def folder_for(session, start, max_depth: int = 25):
    """The folder for a path/loop starting at 'start', or None when nothing around says."""
    w = session.world
    if not start or not w.room(tuple(start)):
        return None
    start = tuple(start)
    idx = _index(session)
    if start in idx:
        return idx[start].most_common(1)[0][0]
    want = area_name(w, start).lower()
    fallback = None
    seen = {start}
    q = deque([(start, 0)])
    while q:
        k, d = q.popleft()
        if k in idx:
            g = idx[k].most_common(1)[0][0]
            if area_name(w, k).lower() == want:
                return g                     # the nearest room of the same area that's in a folder
            if fallback is None and d <= 8:
                fallback = g
        if d >= max_depth or len(seen) > 6000:
            continue
        r = w.room(k)
        for ex in (r.exits.values() if r else ()):
            if ex.to in w.rooms and ex.to not in seen:
                seen.add(ex.to)
                q.append((ex.to, d + 1))
    return fallback


def set_folder(mp, folder: str) -> bool:
    """Move a saved path/loop to another folder: rewrite the folder in its header lines (nothing else in the
    file changes, so a MegaMUD file stays exactly as MegaMUD wrote it)."""
    fn = getattr(mp, "filename", "")
    if not fn or not os.path.exists(fn):
        return False
    folder = folder.replace(":", " ").replace("]", " ").strip()
    with open(fn, encoding="latin-1", newline="") as f:
        lines = f.read().split("\n")
    old = mp.start_group
    for i in (1, 2):
        if i >= len(lines):
            break
        ln = lines[i].rstrip("\r")
        if not (ln.startswith("[") and ln.endswith("]")) or ln.count(":") < 2:
            continue
        code, grp, rest = ln[1:-1].split(":", 2)
        if i == 2 and grp != old and grp.lower() not in GENERIC:
            continue                          # a path ending somewhere else keeps its own end folder
        lines[i] = f"[{code}:{folder}:{rest}]" + ("\r" if lines[i].endswith("\r") else "")
    with open(fn, "w", encoding="latin-1", newline="") as f:
        f.write("\n".join(lines))
    if (mp.end_group or "") == (old or "") or (mp.end_group or "").lower() in GENERIC:
        mp.end_group = folder
    mp.start_group = folder
    return True
