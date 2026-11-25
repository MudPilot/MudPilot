"""Game Data → Monsters attack order: a monster set 'last' is fought after the others in the room, 'first' before
(Dan, 2026-11-24: storm commander / storm giant king are non-hostile bosses — clear the little guys first)."""
import os
import sys
import types

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from mudpilot.config import Settings
from mudpilot.extras import Extras

fails = 0


def check(name, cond):
    global fails
    print(("PASS " if cond else "FAIL ") + name)
    fails += 0 if cond else 1


def pick(cfg, mobs, party=False):
    x = Extras.__new__(Extras)
    x.b = types.SimpleNamespace(cfg=cfg, st=types.SimpleNamespace(party={"a": {}} if party else {}))
    x._leader_target = None
    return [m[0] for m in x.leader_target(mobs)]


room = [("king", {"name": "storm giant king", "exp": 900000}),
        ("giant", {"name": "storm giant", "exp": 90000}),
        ("guard", {"name": "storm guard", "exp": 40000})]

cfg = Settings()
check("default: biggest first", pick(cfg, room)[0] == "king")
cfg.monster_order = {"storm giant king": "last"}
got = pick(cfg, room)
check("king set last: fought after the others", got == ["giant", "guard", "king"])
cfg.monster_order = {"storm giant king": "last", "storm guard": "first"}
check("guard first, king last", pick(cfg, room) == ["guard", "giant", "king"])
check("only the king left: it's still the target", pick(cfg, room[:1]) == ["king"])
cfg.target_biggest = False
cfg.monster_order = {"storm giant king": "last"}
check("biggest-first off: room order, king still last", pick(cfg, room) == ["giant", "guard", "king"])
cfg.target_biggest = True
cfg.monster_order = {}
cfg.attack_leaders_target = True
cfg.monster_order = {"storm giant king": "last"}
x = Extras.__new__(Extras)
x.b = types.SimpleNamespace(cfg=cfg, st=types.SimpleNamespace(party={"a": {}}))
import time
x._leader_target = ("king", time.time())
check("the leader's target still wins", [m[0] for m in x.leader_target(room)][0] == "king")

# the Monsters tab: pick a monster, press Last → saved and shown in the Order column
import tkinter as tk
from mudpilot.session import Session
from mudpilot.gamedata import GameData
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = Settings(); st.save = lambda: None
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
root = tk.Tk(); root.withdraw()
app = type("A", (), {"s": s, "add_log": lambda self, m: None,
                     "_var": lambda self, k: tk.BooleanVar(value=bool(getattr(st, k, False)))})()
gd = GameData(root, app, tab="Monsters")
f = gd.tabs["Monsters"]


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


tree = next(w for w in walk(f) if isinstance(w, tk.ttk.Treeview))
iid = next((i for i in tree.get_children() if tree.set(i, "Name").lower() == "storm giant king"), None)     or tree.get_children()[0]
nm = tree.set(iid, "Name")
tree.selection_set(iid)
last = [b for b in walk(f) if isinstance(b, tk.ttk.Button) and b.cget("text") == "Last"]
last[0].invoke()
check(f"Monsters tab Last button saves it ({nm}: {st.monster_order})", st.monster_order.get(nm.lower()) == "last")
check("…and the Order column shows it", tree.exists(iid) and tree.set(iid, "Order") == "Last")
root.destroy()

print("ALL PASS" if not fails else f"{fails} FAILED")
sys.exit(1 if fails else 0)
