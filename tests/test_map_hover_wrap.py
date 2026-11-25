"""0.8.227 (Dan: hovering a room on the map, 'most of it gets cut off... ok with 2 or 3 lines'): the hover label is
one fact per line, wraps, stays inside the map, and a regen room says when it respawns."""
import os, sys, tempfile, types
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_map_hover"))
import tkinter as tk
from mudpilot import config
from mudpilot.session import Session
from mudpilot.mapview import MapView
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
root = tk.Tk(); root.geometry("630x420+20+20")
m = MapView(root, s, on_goto=lambda k: None, follow=False, width=630, height=420); m.pack(fill="both", expand=True)
m.selected = (17, 2596)
m.scout = ((17, 2596), None)
root.update(); m.redraw(); root.update()
W, H, C = m.winfo_width(), m.winfo_height(), m.CELL
lairs = [k for k in m._pos if s.world.room(k) and s.world.room(k).lair]
check(f"regen rooms on the map ({len(lairs)})", lairs)
# the right-most regen room: the label used to run off this edge
k = max(lairs, key=lambda k: m._pos[k][0])
gx, gy = m._pos[k]
x, y = int(W / 2 + gx * C), int(H / 2 + gy * C)
m._hover(types.SimpleNamespace(x=x, y=y))
root.update()
items = m.find_withtag("tip")
txt = next((m.itemcget(i, "text") for i in items if m.type(i) == "text"), "")
print(txt)
lines = txt.split("\n")
check(f"one fact per line ({len(lines)} lines)", len(lines) >= 2 and lines[0].startswith(f"{k[0]}/{k[1]} "))
check("says it's a regen room", any(l.startswith("Regen room") for l in lines))
check("says when it respawns", any(l.startswith("Respawns in ~") for l in lines))
x0, y0, x1, y1 = m.bbox("tip")
check(f"the label stays inside the map ({x0},{y0})-({x1},{y1}) in {W}x{H}", x0 >= 0 and y0 >= 0 and x1 <= W and y1 <= H)
if os.environ.get("SHOT"):
    from PIL import ImageGrab
    rx, ry = m.winfo_rootx(), m.winfo_rooty()
    ImageGrab.grab((rx, ry, rx + W, ry + H)).save(os.environ["SHOT"])
root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
