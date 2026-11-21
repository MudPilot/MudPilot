"""Goto: the last 5 places you went or loops you ran, at the top (Dan, 2026-11-02). Rego with Hands off on turns
Hands off off ("i rego'd this thing it wont move")."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, gotodlg
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
tmp = tempfile.mkdtemp()
config.board_dir = lambda b: tmp
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st)
check("nothing yet", gotodlg.recent_load(s) == [])
for k in [(1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6)]:
    gotodlg.recent_add(s, "room", k)
gotodlg.recent_add(s, "loop", "Glades nw corner")
gotodlg.recent_add(s, "room", (1, 4))
got = gotodlg.recent_load(s)
check(f"newest first, 5 kept, no repeats ({got})",
      got == [["room", [1, 4]], ["loop", "Glades nw corner"], ["room", [1, 6]], ["room", [1, 5]], ["room", [1, 3]]])

import tkinter as tk
try:
    root = tk.Tk(); root.withdraw()
except tk.TclError:
    print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
app = type("A", (), {"root": root, "s": s})()
p = gotodlg.Picker(app, "goto")
top = p.tree.get_children()
check(f"'Recent' folder at the top ({p.tree.item(top[0], 'text') if top else None})",
      top and "Recent" in p.tree.item(top[0], "text"))
kids = p.tree.get_children(top[0])
check(f"…with the rooms you went to ({len(kids)})", len(kids) >= 4 and p._items[kids[0]] == ("room", (1, 4)))
p.destroy(); root.destroy()
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
