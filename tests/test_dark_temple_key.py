"""Dan, 2026-11-06: going to the Champion of Blood in Black Fort, it "knew to goto the room of change but it missed
acquiring the 3 keys needed to make the dark temple key". The device takes them (MME 'takeitem'), it doesn't check
for them — and each one is a boss's drop, so it goes to the boss, not a farm loop."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import MPath
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g, w = s.bot, s.state, s.world
b.log = lambda m, *a, **k: None
b.send = lambda c, **k: None
KEY = w.item_names["dark temple key"]["num"]
CROSS, RUNED, SKULL = 490, 491, 492           # (a second "skull key" elsewhere: by number)
rc = w.recipe_for(KEY)
check(f"the Room of Change takes the three keys ({rc['needs']})", rc["needs"] == [CROSS, RUNED, SKULL])
g.candidates = [(7, 1240)]
g.carrying = "broadsword"
g.party = {}
mp = MPath(name="Go to 7/1285 Dark Temple, Altar of Blood", author="", start_hash="a", end_hash="b")
todo = b.errands._recipe_todo(KEY, set())
kinds = [(t["kind"], w.item_name(t["num"]), t["room"]) for t in todo]
check(f"each key from its boss, then the device ({kinds})",
      [k for k, *_ in kinds] == ["monster", "monster", "monster", "recipe"]
      and {t["num"] for t in todo[:3]} == {CROSS, RUNED, SKULL}
      and dict((t["num"], t["room"]) for t in todo[:3]) == {CROSS: (7, 1227), RUNED: (7, 1258), SKULL: (7, 1283)})
check("…the keys are dropped from the list if the temple key turns up", all(t["key"] == KEY for t in todo[:3]))
note = b.errands._detour_note(todo, mp)
check(f"the note names them ({note})", "cross key, runed key, skull key" in note)
todo = b.errands._recipe_todo(KEY, {CROSS, SKULL})
check(f"carrying two: only the runed key ({[w.item_name(t['num']) for t in todo]})",
      [t["num"] for t in todo] == [RUNED, KEY])
# the dragon key's fangs (many droppers) are still farmed
dk = b.errands._recipe_todo(w.item_names["dragon key"]["num"], set())
check(f"dragon key: still a farm loop ({[t['kind'] for t in dk]})",
      [t["kind"] for t in dk] == ["farm"] * 5 + ["recipe"])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
