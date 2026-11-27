"""0.8.227.8 (Dan: a box in Game Data → Rooms to untick a boss room "as the character gets bigger and wants to just
roll right in"). The Rooms tab shows each boss room's Stop box (the Bosses tab's list, boss_no_stop); a click flips it,
and the walk then goes straight in (or stops before it again)."""
import os, sys, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_rooms_boss_stop"))
import tkinter as tk
from tkinter import ttk
from mudpilot import config, gamedata
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

st = config.Settings(); st.save = lambda: None; st.boss_no_stop = []
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
logs = []; s.log = lambda m, *a, **k: logs.append(m)
root = tk.Tk(); root.withdraw()
class App: refreshed = 0
app = App(); app.s = s; app.refresh_bosses = lambda: setattr(app, "refreshed", app.refreshed + 1)
gd = gamedata.GameData.__new__(gamedata.GameData); gd.s, gd.app = s, app
nb = ttk.Notebook(root)
f = gd._rooms(nb)
tree = [w for w in f.winfo_children() for w in [w] + list(w.winfo_children()) if isinstance(w, ttk.Treeview)][0]
bar = [w for w in f.winfo_children() for w in [w] + list(w.winfo_children()) if isinstance(w, ttk.Entry)][0]
bar.delete(0, "end"); bar.insert(0, "bosses"); root.update()
rows = tree.get_children()
check(f"'bosses' lists the boss rooms ({len(rows)})", len(rows) > 20)
check("…the stone giant chieftain's tent is one, ticked", tree.set("16/1095", "Stop before boss").startswith("☑ stone giant chieftain"))
# click the cell
root.deiconify(); root.geometry("900x500"); nb.add(f, text="Rooms"); nb.pack(fill="both", expand=True); root.update()
tree.see("16/1095"); root.update()
x = sum(tree.column(c, "width") for c in ("Map/Room", "Name")) + 30
root.update_idletasks(); root.update()
bbox = tree.bbox("16/1095")
cy = bbox[1] + bbox[3] // 2
tree.event_generate("<Button-1>", x=x, y=cy); root.update()
check(f"click: unticked ({tree.set('16/1095', 'Stop before boss')})", tree.set("16/1095", "Stop before boss").startswith("☐"))
check(f"…on the Stop list ({st.boss_no_stop})", "stone giant chieftain" in [n.lower() for n in st.boss_no_stop])
check("…the Bosses tab refreshed, and logged", app.refreshed == 1 and any("Walking straight in" in m for m in logs))
check("…and the walk no longer stops for it", not s.bot._boss_stops((16, 1095)))
tree.event_generate("<Button-1>", x=x, y=cy); root.update()
check("click again: ticked, off the list", tree.set("16/1095", "Stop before boss").startswith("☑") and not st.boss_no_stop)
check("…stops before it again", bool(s.bot._boss_stops((16, 1095))) or not st.stop_before_boss)
bar.delete(0, "end"); bar.insert(0, "Chieftain's Tent"); root.update()
check("a name search shows the box too", tree.set("16/1095", "Stop before boss").startswith("☑"))
root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
