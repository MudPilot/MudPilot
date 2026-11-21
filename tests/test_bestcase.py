"""Best case (Best spots → Best case…): the kit from anything in the game that makes the most exp/hr in an area."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.bestcase import BestCase
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 55
st.char_class, st.char_race = "Mage", "Gnome"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g = s.state
g.level, g.max_hp, g.max_ma, g.ma, g.char_class, g.race = 55, 830, 519, 519, "Mage", "Gnome"
g.ac, g.dr, g.magic_res, g.spellcasting, g.strength, g.agility = 74, 8, 95, 276, 80, 50
g.known_spells = ["mmis", "magm", "simp", "dfir", "dtch"]
g.carrying = "golden headdress (Head), shining metallic robes (Torso), platinum ring (Finger), vortex staff (Weapon Hand)"
w = s.world
mons = [w.monster_names[n] for n in ("nightshade", "drooling geist", "giant spider") if n in w.monster_names]
r = BestCase(s, mons).run()
check(f"runs ({r.get('error')})", not r.get("error"))
check(f"the kit is at least as good ({r['now']:,.0f} → {r['best']:,.0f})", r["best"] >= r["now"])
check(f"suggests changes ({len(r['rows'])})", r["rows"])
from mudpilot import gearcalc as G
ch = BestCase(s, mons).ch
check("every suggestion is usable by a gnome mage of 55",
      all(G.usable(w, row["item"], ch)[0] for row in r["rows"] if row["item"] and row["slot"] != "Weapon"))
check("each says where it comes from", all(row["from"] for row in r["rows"] if row["item"]))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
