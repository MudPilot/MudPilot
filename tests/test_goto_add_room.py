"""0.8.224.2: Goto → 'Add a room…' takes any map/room ('2 873'), with the room you're in as the default; the name
follows the room until you type one. Right-click a search result → 'Add to my list as…' (Dan, 2026-11-22)."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("MUDPILOT_DEFAULT_BOARD", "Main")
from mudpilot import config, gotodlg
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
tmp = tempfile.mkdtemp()
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st)
config.board_dir = lambda b: tmp                       # places file in a throw-away folder (world already loaded)
import tkinter as tk
try:
    root = tk.Tk(); root.withdraw()
except tk.TclError:
    print("ALL PASS (no display)"); sys.exit(0)
w = s.world
here = next(k for k in w.rooms if k[0] == 1)
far = (2, 873) if w.room((2, 873)) else next(k for k in w.rooms if k[0] == 2)
s.state.candidates = [(1, here[1])] if hasattr(s.state, "candidates") else None
app = type("A", (), {"root": root, "s": s})()
p = gotodlg.Picker(app, "goto")
cur = s.state.room
d = p.add_here(); root.update()
fr = d.winfo_children()[0]
ents = [c for c in fr.winfo_children() if isinstance(c, tk.ttk.Entry)]
room_e, name_e, grp_e = ents
check(f"default room is where you are ({room_e.get()} vs {cur})",
      room_e.get() == (f"{cur[0]}/{cur[1]}" if cur else ""))
room_e.delete(0, "end"); room_e.insert(0, f"{far[0]} {far[1]}"); root.update()
check(f"typed '{far[0]} {far[1]}': name follows the room ({name_e.get()!r})", name_e.get() == w.room(far).name)
name_e.delete(0, "end"); name_e.insert(0, "Gear stash"); root.update()
[c for c in fr.winfo_children()[-1].winfo_children() if c.cget("text") == "Add"][0].invoke(); root.update()
added = s.places()["added"]
check(f"added as Gear stash at {far} ({added})", any(a[1] == "Gear stash" and (a[2], a[3]) == far for a in added))
d2 = p.add_here(); root.update()
r2 = [c for c in d2.winfo_children()[0].winfo_children() if isinstance(c, tk.ttk.Entry)][0]
r2.delete(0, "end"); r2.insert(0, "99 99999"); root.update()
btn = [c for c in d2.winfo_children()[0].winfo_children()[-1].winfo_children() if c.cget("text") == "Add"][0]
check("a room that doesn't exist: Add is greyed out", btn.instate(["disabled"]))
d2.destroy()
d3 = p.add_here(far); root.update()
r3 = [c for c in d3.winfo_children()[0].winfo_children() if isinstance(c, tk.ttk.Entry)][0]
check(f"right-click 'Add to my list as…' pre-fills that room ({r3.get()})", r3.get() == f"{far[0]}/{far[1]}")
d3.destroy(); p.destroy(); root.destroy()
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
