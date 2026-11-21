"""Dan, 2026-11-01: auto-collect set in Game Data → Items, like MegaMUD (everybody's coming from MegaMUD). The Items tab's
Auto-get / Never get / Normal buttons write the Loot tab's item rules, and looting follows them."""
import os, sys, time
import tkinter as tk
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamedata import GameData
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"; st.auto_loot = False
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


root = tk.Tk(); root.withdraw()
app = type("A", (), {"s": s, "add_log": lambda self, m: None, "_var": lambda self, k: tk.BooleanVar(value=bool(getattr(st, k, False)))})()
gd = GameData(root, app, tab="Items")
f = gd.tabs["Items"]
def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)
tree = next(w for w in walk(f) if isinstance(w, tk.ttk.Treeview))
iid = next(i for i in tree.get_children() if tree.set(i, "Name") == "rope and grapple")
tree.selection_set(iid)
btns = {b.cget("text"): b for b in walk(f) if isinstance(b, tk.ttk.Button)}
btns["Auto-get"].invoke()
check(f"Auto-get writes a rule ({st.item_rules}) and shows it ({tree.set(iid, 'Get')})",
      "rope and grapple: get" in st.item_rules and tree.set(iid, "Get") == "auto" and st.auto_loot)
g, b = s.state, s.bot
g.candidates = [(1, 16)]
g.view = RoomView("x", {"N"}, [], [(1, "rope and grapple")], [], time.time()); g.view_seq += 1
sent.clear(); b._looted_seq = -1; b.loot()
check(f"…and looting picks it up ({sent})", any("rope and grapple" in c for c in sent))
btns["Never get"].invoke()
check(f"Never get ({st.item_rules})", st.item_rules == ["rope and grapple: never"] and tree.set(iid, "Get") == "never")
btns["Normal"].invoke()
check(f"Normal clears it ({st.item_rules})", not st.item_rules and tree.set(iid, "Get") == "")
root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
