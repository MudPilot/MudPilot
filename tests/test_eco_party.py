"""PVE with Buddy (level 1), 2026-10-28: eco walked past what couldn't hurt the level-55 leader while it beat Buddy,
then meditated next to it. A monster on a party member is a fight; stopped (resting, held), eco doesn't skip.
And who's resting comes from 'par' ("[H: 94%]R"), not an "@mpsync st" telepath."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 55; st.eco_travel = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
rec = s.world.monster_names["orc lieutenant"]
g.candidates = [(1, 1000)]
g.max_hp, g.hp, g.max_ma, g.ma = 830, 820, 519, 500
g.party = {"Miserable": {"t": time.time(), "flags": ""}, "Buddy": {"t": time.time(), "flags": ""}}
g.view = RoomView("Orc Barracks", {"S", "E", "W"}, [("fierce orc lieutenant", rec)], [], ["Buddy"], time.time())
g.view_seq += 1
b.walking, b.loop = True, False
b.path = type("P", (), {"title": "Go to 1/297 Bank", "steps": [], "is_loop": False})()
b._swap = None
mobs = [("fierce orc lieutenant", rec)]
check("walking past a lieutenant that can't hurt a level 55", b._eco_filter(mobs) == [])
b.note_line("The fierce orc lieutenant all-out slashes Buddy for 42 damage!")
check("…it hits Buddy: now it's a fight", b._eco_filter(mobs) == mobs)
b._aggro = {}
g.resting = True
check("resting with it in the room: fight it, don't walk past", b._eco_filter(mobs) == mobs)
g.resting = False
# resting from 'par'
ps = s.partysync
ps.peers = {"Buddy": {"rest": 0, "t": time.time()}}
g.party["Buddy"]["flags"] = "R"
check("'par' shows Buddy resting (R)", ps.peer_resting() == "Buddy")
g.party["Buddy"]["flags"] = ""
check("…and up again", ps.peer_resting() is None)
st.party_sync = True
s.telnet.sock = object(); s._entered = True
ps.asked = {"buddy"}
sent.clear(); g.resting = True; ps.tick(); g.resting = False; ps.tick()
check(f"no '@mpsync st' telepaths ({sent})", not any("@mpsync st" in c for c in sent))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
