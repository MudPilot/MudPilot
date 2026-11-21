"""Buddy, 2026-11-02, Go to the Darkwood tree house (1/2305): the door west of 1/2304 ('[6 picklocks/strength]') is
locked and the only way in. His strength wasn't read yet, so he counted himself too weak, sent 'open west' ~20 times
waiting for Revolution and Evolution to bash, then 'went round' into "MME's map has no way into that area". Dan:
"Need to bash if its closed." """
import os, re, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"; st.char_level = 20
st.bash_doors_first = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g, b, w = s.state, s.bot, s.world
g.level, g.picklocks, g.strength, g.max_hp, g.hp = 20, 0, 0, 300, 300       # strength not read yet
g.party = {"Buddy": {}, "Revolution": {}, "Evolution": {}}
s.partysync.command("Revolution", "me lvl=20 str=60 cls=Priest")
s.partysync.command("Evolution", "me lvl=20 str=50 cls=Druid")
s.partysync.members = lambda: ["Buddy", "Revolution", "Evolution"]
b.x.leading = lambda: True
s.comeback.leading = lambda: True
door, inside = (1, 2304), (1, 2305)
g.candidates = [door]
g.view = RoomView("Darkwood Forest, Clearing", {"E", "W"}, [], [], [], time.time())   # they walk in after the look
check("Go to the tree house", b.goto(inside))
b._locked_dir = "W"; b._lock_tries = {}; b._unlocked = None
sent.clear(); b._cool.clear()
for _ in range(30):
    b._door_wait_until = 0
    if b._locked_dir is None:
        b._locked_dir = "W"
    try:
        b.walk([], True)
    except Exception as e:
        print("walk:", e)
    if not b.walking:
        break
bashes = [c for c in sent if c.lower().startswith("bash")]
check(f"strength not known: bashes it himself ({len(bashes)}, {sorted(set(sent))})", len(bashes) >= 20 and sent.count("open west") <= 1)
check(f"the only way in: still at it, no 'no route' stop ({b.status})", b.walking and b._lock_tries.get("W", 0) > 20)
check("…and the door isn't marked failed", (door, "W") not in (getattr(w, "failed_edges", None) or {}))
check(f"strength unknown at a door that says what it needs: 'st' first ({sent[:2]})", sent and sent[0] == "st")

# Buddy, 2026-11-02 (Dan: "the door going down to prismatic dragon in ancient ruin is not bashable, mp tried to bash
# it about 20 times"): 3/592 down, '[201 picklocks/strength]' — nobody in the party is that strong
b.stop("test"); g.strength = 80
s.partysync.members = lambda: ["Buddy", "Revolution", "Evolution"]
pd = (3, 592)
check(f"the prismatic dragon's door is 200+ ({w.room(pd).exits['D'].etype})", re.search(r"\[[23]0\d picklocks",w.room(pd).exits["D"].etype))
g.candidates = [pd]
g.view = RoomView(w.room(pd).name, set(w.room(pd).exits), [], [], ["Revolution", "Evolution"], time.time())
b._bash_help = None
sent.clear()
b._party_bash("D")
check(f"helpers too weak for it aren't asked to bash ({sent})", not any("@do" in c for c in sent))
b._locked_dir = "D"; b._lock_tries = {}; b._unlocked = None; b._door_st = None
b.walking, b.path = True, type("P", (), {"steps": [], "title": "old path", "is_loop": False, "filename": "",
                                         "needed_item": ""})()
b.route_around = lambda *a: False
sent.clear()
for _ in range(10):
    b._door_wait_until = 0
    try:
        b.walk([], True)
    except Exception as e:
        print("walk:", e)
    if not b.walking:
        break
check(f"no bashing a door he can't open ({sent})", not any(c.startswith("bash") for c in sent))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
