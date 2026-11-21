"""PVE, 2026-10-28: Go to Dragon's Teeth Hills from the Pier crossed a river (needs a log raft) and went 220 rooms
the other way to the raft shop. A way round the water ~20 rooms longer: walk that, no raft."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g.carrying = "25 runic coins, vortex staff (Weapon Hand), magical quartz rod"
b.held_items = lambda: set()
w = s.world
direct = w.route((1, 1813), (2, 873), level=55)
r = b.plan_route((1, 1813), (2, 873))
av = b.avoid_set()
check(f"takes a dry way that keeps out of avoided areas ({len(r)} rooms; direct {len(direct)} crosses "
      f"{sum(e.to in av for e in direct)} avoided)", r and not b._needy_rooms((1, 1813), r, set())
      and not any(e.to in av for e in r))
mp_needs = b._needy_rooms((1, 1813), direct, set())
check(f"…the direct way did need a raft ({len(mp_needs)} water rooms)", mp_needs)
# Dan, 2026-10-30: you carry a raft, the party doesn't (they're heavy) — still the dry way
raft = next(n for n, it in w.items.items() if it.get("name") == "log raft")
b.held_items = lambda: {raft}
g.party = {"Miserable": {}, "Buddy": {}, "Evolution": {}}
w.forget_routes()
r2 = b.plan_route((1, 1813), (2, 873))
check(f"with a party: dry even though you have a raft ({len(r2)} rooms)", r2 and not b._needy_rooms((1, 1813), r2, set()))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
