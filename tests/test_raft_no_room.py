"""0.8.227.2 (Dan: "pvp miserable just took a different path to exquisite weapons in kingsport, needing a raft...
nobody could carry one since we're hauling cudgels so it stopped... confirm everybody has room in their inventory for
rafts, if they don't it needs to plan a dry path if one's available"). Here: Tagesh Plateau, Highland Cross (14/5290)
with its NE, SW and E exits marked failed (the too-heavy refusals did that) — the short way crosses the river."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_raft_no_room"))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 52
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
logs = []
s.log = lambda m, *a, **k: logs.append(m)
b, g, w = s.bot, s.state, s.world
g.level = 52
b.held_items = lambda: set()
g.party = {"Miserable": {}, "Revolution": {}}
def wet(a, route):
    return bool(b._needy_rooms(a, route or [], set()))
# (the plain shortest way 14/4379 → 14/4672, taken before any planning turns on the danger/boss rules: over water)
wet_r = w.route((14, 4379), (14, 4672), level=b.route_level(), have=set(b.every_item()))
# the way Dan walks it: no failed exits, no water
r = b.plan_route((14, 5290), (14, 1782))
check(f"Tagesh Plateau → Exquisite Weaponry: dry ({len(r or [])} rooms)", r and not wet((14, 5290), r))
# its NE, SW, E marked failed (what the too-heavy refusals did): no dry way left — the raft, room or not
for d in ("NE", "SW", "E"):
    w.fail_edge((14, 5290), d)
g.enc = (4906, 4939, "Heavy", 99); g.coins = {}
r = b.plan_route((14, 5290), (14, 1782))
check(f"…with those exits failed there's no dry way: the river ({len(r or [])} rooms)", r and wet((14, 5290), r))
# the dry-route pass itself: 46 rooms by a climb you need a harness for vs 116 round it (more than its 'about double' cap, 106)
src, dst = (14, 4379), (14, 4672)
b._raft_trip = lambda *a, **k: 0          # (as if a raft shop were close: only the 'about double' cap counts)
w.failed_edges.clear(); w.forget_routes()
check(f"the short way needs a harness carried ({len(wet_r or [])} rooms)", wet_r and wet(src, wet_r))
g.enc = (4000, 4939, "Heavy", 81); g.coins = {}
r = b._dry_route(src, dst, wet_r)
check(f"room for one: that way stays ({len(r or [])} rooms)", r and wet(src, r))
g.enc = (4906, 4939, "Heavy", 99); g.coins = {"gold crown": 30}
r = b._dry_route(src, dst, wet_r)
check(f"no room (33 free + 10 from coins): the long way round ({len(r or [])} rooms)", r and not wet(src, r))
check("…and it says why", any("you've room for" in l for l in logs))
g.enc = (4000, 4939, "Heavy", 81)
b.note_no_room("climbing harness")    # (this one's a climb, not water: the same rule)
r = b._dry_route(src, dst, wet_r)
check(f"a party member had no room for one lately: the dry way ({len(r or [])} rooms)", r and not wet(src, r))
b._no_room = {k: time.time() - b.NO_ROOM_SECS - 1 for k in b._no_room}
r = b._dry_route(src, dst, wet_r)
check("…half an hour later: the short way again", r and wet(src, r))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
