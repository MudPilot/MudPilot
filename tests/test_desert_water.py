"""Dan, 2026-11-04: "i just sent myself to scorching desert, we need waterskins until we have completed the sunstone
wristband … it didn't ask the party if they had a sunstone wristband or waterskins so i assume it doesn't know."
The desert's room spell (683, 'failspell 711 …') leaves alone whoever drank from a waterskin (it casts 711); its rolls
check for the sunstone wristband. So a walk through it needs either, like a raft for a river — and you drink."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
w, b = s.world, s.bot
skin, band = w.item_names["waterskin"]["num"], w.item_names["sunstone wristband"]["num"]
check(f"the desert spell wants a waterskin or the wristband ({sorted(w.spell_items(683))})",
      w.spell_items(683) == frozenset({skin, band}))
check("a river still wants just a raft (unchanged)", w.item_names["log raft"]["num"] in
      next(iter(w.spell_items(sp) for (k, sp) in w.room_spells.items() if w.spell_items(sp)
                and w.spells[sp]["Name"].lower().startswith("river")), set()))
# a walk into the desert: the item check finds it missing, and picks the waterskin (a shop sells it)
desert = next(k for k, r in w.rooms.items() if r.name == "Scorching Desert" and w.room_spells.get(k) == 683)
nb = next(iter(w.room(desert).exits.values())).to
ex_in = next(e for e in w.room(nb).exits.values() if e.to == desert)
needs = w.carry_needs([(nb, ex_in)])
check(f"walking in: each walker needs one of them ({needs})", needs == [frozenset({skin, band})])
check("…and the one to get is the waterskin (a shop sells it)", b.carry_pick(needs[0]) == skin)
# in the desert: drink on the way in, and when the heat gets you
sent, logs = [], []
b.send = lambda c, **k: sent.append(c)
b.log = lambda m, *a, **k: logs.append(m)
s.state.candidates = [desert]
b.held_items = lambda: {skin}
b._desert_drink("Scorching Desert")
check(f"drinks coming in ({sent})", sent == ["use waterskin"])
b._desert_drink("Obvious exits: north")
check("not again straight away", sent == ["use waterskin"])
b._drank_at = time.time() - 700
b._desert_drink("Scorching Desert, Pyramid")
check("still in the desert after 600 s: no use on a timer (3 uses only)", sent == ["use waterskin"])
b._drank_at = time.time() - 60
b._desert_drink("You suffer in the desert heat...")
check(f"drinks when the heat gets you ({sent})", sent == ["use waterskin", "use waterskin"])
sent.clear()
b._drank_at = 0
b.held_items = lambda: {skin, band}
b._desert_drink("You suffer in the desert heat...")
check("wearing the wristband: doesn't drink", sent == [])
b.held_items = lambda: set()
b._desert_drink("You suffer in the desert heat...")
check(f"no waterskin: says so ({logs[-1:]})", sent == [] and "no waterskin" in logs[-1])
s.state.candidates = [(1, 1)]
b.held_items = lambda: {skin}
b._drank_at = 0
b._desert_drink("You suffer in the desert heat...")
check("outside the desert: nothing", sent == [])
s.state.candidates = [desert]
b._drank_at = time.time() - 300
b._desert_drink("Scorching Desert")
check("back in within 600 s of the last one: no use", sent == [])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
