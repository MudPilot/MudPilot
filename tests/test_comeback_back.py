"""Pyramid, 2026-10-28: comeback set off 313 steps back to the tomb where it last saw Revolution, and kept going
after he'd re-joined a second later. Back in the party → call the search off; in the room → invite, don't go."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.party_comeback = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g, cb = s.bot, s.state, s.comeback
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g.candidates = [(12, 2459)]
g.view = RoomView("Temple Sanctum", {"N"}, [], [], [], time.time()); g.view_seq += 1
cb.fetch = {"name": "Revolution", "phase": "going", "room": (12, 2250), "back": None, "t": time.time(), "searched": 1}
cb.missing = {"Revolution": {"t": time.time(), "why": "left behind"}}
b.walking, b._goto_target = True, (12, 2250)
b.path = type("P", (), {"title": "Go to 12/2250 Tomb of the Pharaoh", "steps": []})()
g.party = {"Miserable": {"t": time.time()}, "Revolution": {"t": time.time() + 1}}   # re-read: he joined
cb.tick()
check(f"he's back in the party: search off, walk stopped ({b.walking}, {cb.fetch})", not cb.fetch and not b.walking)
# asked @where, no answer, but he's standing here: invite, don't walk off
g.party = {"Miserable": {}}
g.view = RoomView("Temple Sanctum", {"N"}, [], [], ["Revolution"], time.time()); g.view_seq += 1
cb.fetch = {"name": "Revolution", "phase": "asked", "room": None, "back": None, "t": time.time() - 11}
sent.clear(); cb.tick(); cb.tick()
check(f"here in the room: invite, no trip ({sent}, {cb.fetch['phase']})", "invite Revolution" in sent and cb.fetch["phase"] == "asked")
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
