"""0.8.190 (Dan, "idol for each follower"): leading a party, the Earthen Catacombs' idol teleport (16/2273 east —
'checkitem 1281', else you land in 16/2228) or any exit every walker needs their own item for is planned only when
every follower is known to carry the item: their MudPilot says so (party sync 'kit='), or they answered '@have'
yes. Otherwise another way — into the Lost City that's one with keys fetched / doors picked; with no other way at
all, as before (the party's '@have' round): 16/2273 → 16/2431 itself has none."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_party_idol"))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55; st.auto_combat = True
st.avoid_mode = "allow"      # (the way without the idol crosses the Negative Power Plane)
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda m, *a, **k: None
b, w, g = s.bot, s.world, s.state
g.level, g.carrying, g.keys = 55, "", "golden idol"
IDOL = 1281
def idol_way():
    s.route_char()
    w.forget_routes()
    r = b.plan_route((16, 1412), (16, 356))
    cur, used = (16, 1412), False
    for x in r or []:
        used |= cur == (16, 2273) and x.dir == "E"
        cur = x.to
    return r, used
r, used = idol_way()
check(f"alone with the idol, Abandoned Temple → Deranged Priest: through the teleport ({len(r) if r else None} rooms)",
      used)
check(f"the idol is one of the carry-for-everyone items ({IDOL in w.carry_item_set()})", IDOL in w.carry_item_set())
check(f"…and our party sync says we carry it ({s.partysync.my_info()})", "kit=1281" in s.partysync.my_info())
g.party = {"Tester": {}, "Revolution": {}}
s.partysync.members = lambda: ["Revolution"]
ROPE = 191                     # (the way without the idol climbs down with rope and grapple: each walker needs one)
s.partysync.info = lambda: {"Revolution": {"kit": [ROPE]}}
r, used = idol_way()
check(f"leading Revolution, who might have no idol: another way ({len(r) if r else None} rooms)", r and not used)
s.partysync.info = lambda: {"Revolution": {"kit": [IDOL, ROPE]}}
r, used = idol_way()
check("his MudPilot says kit=1281: the teleport", used)
s.partysync.info = lambda: {"Revolution": {"kit": [ROPE]}}
r, used = idol_way()
check("kit=191 (rope, no idol): another way", r and not used)
s.partysync.info = lambda: {}
b.errands.known_have[("revolution", ROPE)] = (True, time.time())
b.errands.known_have[("revolution", IDOL)] = (True, time.time())
r, used = idol_way()
check("he answered '@have golden idol' yes: the teleport", used)
b.errands.known_have[("revolution", IDOL)] = (False, time.time())
r, used = idol_way()
check("…he said no: another way", r and not used)
s.partysync.info = lambda: {}
b.errands.known_have.clear()
r = b.plan_route((16, 2273), (16, 2431))
check(f"nobody known to carry anything, no other way at all (16/2273 → 16/2431): the teleport, as before ({len(r) if r else None})", r and len(r) == 1)
s.partysync._note_me("Revolution", "lvl=50 hp=900 cls=Druid kit=1281")
s.partysync.info = type(s.partysync).info.__get__(s.partysync)
s.partysync.members = lambda: ["Revolution"]
check(f"a follower's 'me … kit=1281' is read ({s.partysync.info().get('Revolution', {}).get('kit')})",
      s.partysync.info().get("Revolution", {}).get("kit") == [IDOL])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
