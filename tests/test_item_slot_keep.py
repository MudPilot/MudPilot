"""0.8.224.3 (R: logs): after wear/remove lines the hands keep their slot names, so an item spell that needs a
two-hander still takes the off-hand item off first (PVEREV's divine intervention failed 217 of 221 times)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot.gamestate import GameState, worn_list, wielded
from mudpilot import itemspells
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = GameState.__new__(GameState)
st.carrying = "iron emblem (Worn), golden chalice (Off-Hand), platinum sceptre (Weapon Hand), emerald-tipped crozier, mine pass"
for ln in ["You have removed golden chalice.", "You have removed platinum sceptre.", "You are now holding emerald-tipped crozier.",
           "You have removed emerald-tipped crozier.", "You are now holding platinum sceptre.", "You are now wearing golden chalice."]:
    GameState._inv_delta(st, ln)
check(f"after a swap: still wielding the sceptre ({wielded(st.carrying)!r})", wielded(st.carrying) == "platinum sceptre")
check("…and the chalice is still the off-hand item", ("golden chalice", "Off-Hand") in worn_list(st.carrying))
class W: pass
w = W()
w.gear = {1: {"name": "emerald-tipped crozier", "Worn": 1, "WeaponType": 1, "UseCount": -1, "abils": {43: 5}},
          2: {"name": "golden chalice", "Worn": 12}, 3: {"name": "platinum sceptre", "Worn": 1, "WeaponType": 0}}
w.spells = {5: {"Name": "divine intervention"}}
want = ['remove golden chalice', 'eq emerald-tipped crozier', 'use emerald-tipped crozier', 'eq platinum sceptre', 'eq golden chalice']
check("divine intervention after a swap: chalice off first, back after", itemspells.expand(w, "#etc", st.carrying) == want)
generic = "iron emblem (Worn), golden chalice (Worn), platinum sceptre (Worn), emerald-tipped crozier"
check("slots shown only as (Worn): MME's slot decides", itemspells.expand(w, "#etc", generic) == want)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
