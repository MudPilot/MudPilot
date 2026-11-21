"""0.8.200: stat and mana-regen breakpoints."""
import os, sys, types, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import statbreaks as sb
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

dodge = next(c for c in sb.columns("Agility", 50, True) if c[0] == "Dodge")[2]
check(f"Dodge steps at 53, 56 from 50 ({sb.next_steps(dodge, 50)})", sb.next_steps(dodge, 50) == [(53, 1), (56, 2)])
check("below 50 it's negative and truncates toward zero", dodge(48) == 0 and dodge(47) == -1)
# mage, level 50, INT 120, magery 3: (70 × 120 × 5) ÷ 1650 = 25
check(f"mana tick ({sb.mana_tick(50, 120, 0, 0, 1, 3)})", sb.mana_tick(50, 120, 0, 0, 1, 3) == 25)
check("Paradigm: +50% → 37", sb.mana_tick(50, 120, 0, 0, 1, 3, 50, para=True) == 37)
check("Stock: +50% → 37", sb.mana_tick(50, 120, 0, 0, 1, 3, 50, para=False) == 37)
bp = sb.regen_breakpoints(50, 120, 0, 0, 1, 3, base_pct=10, lo=0, hi=60)
check(f"regen steps: each a higher tick ({bp[:4]})", all(b[1] > a[1] for a, b in zip(bp, bp[1:])) and bp[0][0] == 0)
check("a class with no mana: 0", sb.mana_tick(50, 120, 120, 120, 0, 0) == 0)

# the window builds from a stub app
import tkinter as tk
root = tk.Tk(); root.withdraw()
st = types.SimpleNamespace(level=50, char_class="Mage", strength=60, intellect=120, willpower=70, agility=80,
                           health=70, charm=60, picklocks=0,
                           abil_value=lambda n, src="total": (60, time.time()) if src == "total" else (46, time.time()))
app = types.SimpleNamespace(s=types.SimpleNamespace(state=st, settings=types.SimpleNamespace(board="Paradigm", char_level=50),
                                                    world=types.SimpleNamespace(classes={5: {"Name": "Mage", "MageryType": 1,
                                                                                             "MageryLVL": 3}})))
f = sb.make_pane(root, app)
f.pack()
root.update()
trees = [w for w in f.winfo_children()[2].winfo_children()[0].winfo_children() if w.winfo_class() == "Treeview"]
rows = trees[0].get_children() if trees else []
check(f"Intellect table filled ({len(rows)} rows)", len(rows) >= 4)
root.destroy()
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
