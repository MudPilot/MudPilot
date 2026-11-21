"""Miserable PVE (Dan, 2026-11-03): flipping magma blast / sphere of implosion / forked lightning on the same monsters.
magm 5 mana × 6 a round = 30 for ~500, simp 25 for ~440, fork 2 × 10 = 20 for ~350 — the same damage per mana, so
stepping down only costs damage. Step down only for a real saving (15% more damage per mana)."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.spell_eff_max_steps = 3; st.spell_eff_floor_pct = 40
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, sb = s.bot, s.spellbook
magm, simp, fork = sb.find("magm"), sb.find("simp"), sb.find("fork")
check(f"a round of each: magm {b._round_mana(magm)}, simp {b._round_mana(simp)}, fork {b._round_mana(fork)}",
      (b._round_mana(magm), b._round_mana(simp), b._round_mana(fork)) == (30, 25, 20))
s.spelltune.level = lambda name: 2                # the tuner wants two steps down
s.spelltune.note_ladder = lambda *a: None
rows = {"magm": (magm, 504, 0.9, "single", ""), "simp": (simp, 442, 0.9, "single", ""), "fork": (fork, 345, 0.9, "single", "")}
order = ["magm", "simp", "fork"]
def pick(excl=()):
    for k in order:
        if rows[k][0]["Number"] not in excl:
            return rows[k]
    return None
got = b._dial_back(rows["magm"], {"name": "basilisk", "exp": 50000, "hp": 500}, False, "damage", pick)
check(f"500 HP: magm 30 mana / simp 50 / fork 30 — stays on magma blast ({got[0]['Short'] if got else None})", got and got[0] is magm)
# a real saving still steps down: a 10-mana spell for 400
cheap = dict(simp, ManaCost=10)
rows["simp"] = (cheap, 400, 0.9, "single", "")
got = b._dial_back(rows["magm"], {"name": "basilisk", "exp": 50000, "hp": 500}, False, "damage", pick)
check(f"kills it for 20 mana against 30: steps down ({got[0]['Short'] if got else None})", got and got[0] is cheap)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
