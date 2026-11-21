"""Dan, 2026-11-01: "I wanted to walk it on the map without walking it in game, it's a hell of a lot faster." Record
Loop on the Map window: the number pad walks a pen round the map from the room you clicked; nothing is sent."""
import os, sys, types
import tkinter as tk
from tkinter import ttk
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.mapview import MapView
from mudpilot.roominfo import RecordBar
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


w = s.world
start = (17, 16)
# a little loop from 17/16: find one with BFS over plain exits
import collections
def loop_from(a, maxlen=8):
    q = collections.deque([(a, [])])
    while q:
        k, p = q.popleft()
        if len(p) >= maxlen:
            continue
        for d, ex in w.room(k).exits.items():
            if ex.kind not in ("normal", "door") or not ex.to or not w.room(ex.to):
                continue
            if ex.to == a and len(p) >= 2:
                return p + [d]
            if ex.to not in [w.room(a)] and len(p) < maxlen:
                q.append((ex.to, p + [d]))
    return None
dirs = loop_from(start)
check(f"a loop to draw from 17/16 ({dirs})", dirs)
root = tk.Tk(); root.withdraw()
top = tk.Toplevel(root)
bar = ttk.Frame(top); bar.pack()
app = types.SimpleNamespace(s=s)
m = MapView(top, s, on_goto=lambda k: None, follow=False); m.pack()
m.selected = start                                   # the room you clicked
rb = RecordBar(bar, app, m)
rb._start("loop")
check(f"drawing starts at the clicked room ({s.routerec.start})", s.routerec.start == start and s.routerec.draw)
inv = {v: k for k, v in rb.PEN_KEYS.items() if k not in "+-"}
for d in dirs:
    e = types.SimpleNamespace(widget=m, keysym=f"KP_{inv[d]}" if inv[d] != "." else "KP_Decimal", keycode=0, state=0)
    rb._key(e)
check(f"the number pad walked the pen round ({s.routerec.steps()} steps)", s.routerec.steps() == len(dirs))
check(f"nothing sent to the game ({sent})", not [c for c in sent if c.strip()])
check("back at the start: a loop", s.routerec.back_at_start())
mp, err = s.routerec.build("Test loop")
check(f"it builds a loop ({err or len(mp.steps)})", mp and len(mp.steps) == len(dirs))
root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
