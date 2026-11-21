"""0.8.201 (Dan): cheap hazard counters — "Hazard counters i like lets implement that without spending tons of cash…
I dont want to go buy a 20 runic item to minimize minimal damage." Off by default, with a gold cap (300). A path
through rooms that hurt (Khazarad's swamp poison, 20 a room) gets the cheapest shop item MME says negates it (swamp
boots) when the damage it saves is real; one you carry comes first; dearer ones are only mentioned."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_hazard_counters"))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route
from mudpilot.hazards import advise, extra_buys, path_damage, counters
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 40
check("off by default, 300-gold cap", st.hazard_counters is False and st.hazard_counter_cap == 300)
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
logs = []
s.log = lambda m, *a, **k: logs.append(m)
sent = []
s.send = lambda c, *a, **k: sent.append(c)
b, w, g = s.bot, s.world, s.state

swamp = next(sp for sp in set(w.room_spells.values()) if (w.spells.get(sp) or {}).get("Name") == "swamp poison")
boots = next(n for n, it in w.items.items() if it.get("name") == "swamp boots")
check(f"MME: swamp boots negate swamp poison ({[w.items[c]['name'] for c in counters(w, swamp)]})",
      boots in counters(w, swamp))
A, B = (6, 251), (6, 286)
r = w.route(A, B)
mp = path_from_route(w, A, r, name=f"Go to {B[0]}/{B[1]}")
dmg = path_damage(w, mp.steps)
check(f"{A} → {B}: {len(r)} rooms, swamp poison adds up ({dmg.get(swamp)})", dmg.get(swamp, (0, 0))[0] >= 100)


def setup(carry="torch", max_hp=400, cap=300, auto=True, on=True):
    st.hazard_counters, st.hazard_counter_cap, st.auto_get_items = on, cap, auto
    g.set_room(A)
    g.carrying, g.keys, g.max_hp, g.hp, g.level, g.wealth = carry, "", max_hp, max_hp, 40, 1_000_000
    g.party = {}
    b._picked_items = set()
    b._goto_target = B
    b.__dict__.pop("_hazard_said", None)
    b.__dict__.pop("_hazard_tried", None)
    del logs[:]


setup(on=False)
check("setting off: nothing", advise(b, mp) == {"buy": [], "notes": []})

setup()
adv = advise(b, mp)
check(f"on, no counter carried: buys swamp boots ({adv})", adv["buy"] == [boots]
      and any("swamp boots" in n and "gold" in n for n in adv["notes"]))
check("…and says to wear them (MudPilot won't swap your gear)", any("wear it" in n for n in adv["notes"]))

setup(carry="swamp boots (Feet)")
check("wearing swamp boots already: nothing to buy", advise(b, mp)["buy"] == [])
setup(carry="trollskin boots")
check("another counter carried (trollskin boots): nothing to buy", advise(b, mp)["buy"] == [])

setup(cap=100)
adv = advise(b, mp)
check(f"cap below the price: not bought, only mentioned ({adv['notes']})", adv["buy"] == []
      and any("over the 100-gold cap" in n for n in adv["notes"]))

setup(max_hp=2000)
adv = advise(b, mp)
check(f"small next to your HP (2000): not worth it, not even a note ({adv})", adv == {"buy": [], "notes": []})

setup(auto=False)
adv = advise(b, mp)
check(f"'go get it first' off: only says what and where ({adv['notes']})", adv["buy"] == []
      and any("swamp boots" in n and "gold at" in n for n in adv["notes"]))

# a river needs a raft — that's a must-have already (carry_needs), not a hazard counter
river = next(k for k, sp in w.room_spells.items() if (w.spells.get(sp) or {}).get("Name") == "river damage")
rsp = w.room_spells[river]
from mudpilot.megamud_files import Step
fake = [Step("", 0, "N", [], None, river)] * 10
check("river rooms (a raft is a must) aren't counted here", rsp not in path_damage(w, fake))

setup(carry="")
g.carrying = None
check("inventory not read yet: no guessing", advise(b, mp)["buy"] == [])

# extra_buys: says it once; asks at most twice a half hour
setup()
first = extra_buys(b, mp)
second = extra_buys(b, mp)
third = extra_buys(b, mp)
check(f"extra_buys: twice (the 'i' re-read, then the errand), then not again ({first}, {second}, {third})",
      first == [boots] and second == [boots] and third == [])
check("…the note said once", sum("swamp boots" in l for l in logs) == 1)

# start_path: the boots go on the errand before the walk
setup()
st.check_needed_items = True
g.inv_at = time.time()
b.errands.active = None
b.start_path(mp)
ea = b.errands.active
check(f"start_path: an errand buys the boots first ({[t['num'] for t in (ea or {}).get('todo') or []]})",
      ea and any(t["num"] == boots and t["kind"] == "shop" for t in ea["todo"]))
b.errands.active = None
b.walking, b.path = False, None

setup(on=False)
g.inv_at = time.time()
b.start_path(mp)
check("start_path with the setting off: no errand, walks", b.errands.active is None and b.path is mp)
b.walking, b.path = False, None

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
