"""Dan, 2026-11-16: in Game Data → Items, click Get to see everything on auto-grab at the top; Slot and Type sort too.
All of the realm's items are listed (it used to stop at 2,000)."""
import os, sys
import tkinter as tk
from tkinter import ttk
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamedata import GameData
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
st.item_rules = ["rope and grapple: get", "runed stone cudgel: get, stash", "silver dagger: never"]
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


root = tk.Tk(); root.withdraw()
app = type("A", (), {"s": s, "add_log": lambda self, m: None, "_var": lambda self, k: tk.BooleanVar(value=False)})()
gd = GameData(root, app, tab="Items")
f = gd.tabs["Items"]
def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)
t = next(w for w in walk(f) if isinstance(w, ttk.Treeview))
kids = t.get_children()
check(f"every item listed ({len(kids)} of {len(s.world.gear)})", len(kids) == len(s.world.gear))

def heads(col, n):
    return [t.set(k, col) for k in t.get_children()[:n]]

from mudpilot.gamedata import _sort
n = sum(1 for k in t.get_children() if t.set(k, "Get"))
_sort(t, "Get")
check(f"Get: the {n} items with a rule come first ({heads('Get', n)})",
      n >= 2 and all(heads("Get", n)) and not t.set(t.get_children()[n], "Get"))
first = heads("Get", n)
_sort(t, "Get")
check(f"Get again: flipped, blanks still last ({heads('Get', n)})",
      heads("Get", n) == first[::-1] and not t.set(t.get_children()[n], "Get"))
_sort(t, "Slot")
check(f"Slot: blanks last ({heads('Slot', 2)} … '{t.set(t.get_children()[-1], 'Slot')}')",
      all(heads("Slot", 2)) and t.set(t.get_children()[-1], "Slot") == "")
sl = [t.set(k, "Slot") for k in t.get_children() if t.set(k, "Slot")]
check("Slot: in order", sl == sorted(sl, key=str.lower))
_sort(t, "Type")
ty = [t.set(k, "Type") for k in t.get_children()]
check(f"Type: grouped ({ty[0]} … {ty[-1]})", ty == sorted(ty, key=str.lower))
root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
