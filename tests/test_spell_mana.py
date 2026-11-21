"""Dan, 2026-11-01: click a spell in Game Data → Spells to see what it does, and set its mana cost — power-levelling,
the little ones should 'cast' (engage, earn their share) even without the mana; the spell just never goes off."""
import os, sys, time
import tkinter as tk
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.spells import describe
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
st.spell_mana = {"1110": 0}                               # sleep: cast it whatever the mana
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


sp = s.world.spells[1110]
check(f"your mana cost applies at start ({sp['ManaCost']}, MME {sp['_mme_mana']})", sp["ManaCost"] == 0 and sp["_mme_mana"] == 18)
check("…and the description says so", "MME says 18" in describe(s.world, sp, 20))
s.reload_world()
check("…and after the map's reloaded", s.world.spells[1110]["ManaCost"] == 0)
d = describe(s.world, s.world.spells[1377], 50)
check(f"serenity described ({d.splitlines()[1]})", "Serenity" in d and "ManaRgn" in d and "Lasts" in d)
# the Spells tab: click shows it; Set mana / MME's cost
from mudpilot.gamedata import GameData
from mudpilot import gamedata as GDm
root = tk.Tk(); root.withdraw()
app = type("A", (), {"s": s, "add_log": lambda self, m: None,
                     "_var": lambda self, k: tk.BooleanVar(value=bool(getattr(st, k, False)))})()
gd = GameData(root, app, tab="Spells")


def walk(w):
    yield w
    for c in w.winfo_children():
        yield from walk(c)


f = gd.tabs["Spells"]
tree = next(w for w in walk(f) if isinstance(w, tk.ttk.Treeview))
info = next(w for w in walk(f) if isinstance(w, tk.Text))
btns = {b.cget("text"): b for b in walk(f) if isinstance(b, tk.ttk.Button)}
tree.selection_set("1377"); root.update()
check("clicking a spell shows what it does", "Serenity" in info.get("1.0", "end"))
GDm.simpledialog.askinteger = lambda *a, **k: 5
btns["Set mana cost…"].invoke()
check(f"Set mana cost → 5 ({st.spell_mana}, column {tree.set('1377', 'Mana')})",
      st.spell_mana.get("1377") == 5 and s.world.spells[1377]["ManaCost"] == 5 and tree.set("1377", "Mana") == "5*")
btns["MME's cost"].invoke()
check("MME's cost puts it back", "1377" not in st.spell_mana and s.world.spells[1377]["ManaCost"] == 30)
root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
