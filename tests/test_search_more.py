"""Dan, 2026-10-30: 1/1070 Crypt, Small Chamber — 'search s' three times found nothing and it gave up ('No walkable
route'). Half-ogres and kang (low Int) can take 4 or 5. After 3: look, make sure it's the right room and the exit is
still hidden, then search on (up to 8)."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Kang"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
sent = []
b.send = lambda c, *a, **k: sent.append(c)
b.route_around = lambda *a: (sent.append("ROUND") or True)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


R = (1, 1070)
g.candidates = [R]
pre = ["search s"]
b._search_wait = None
b._search_gate(pre, "S", R)
for _ in range(2):
    b._search_line("You notice nothing different to the south.")
    b._search_gate(pre, "S", R)
b._search_line("You notice nothing different to the south.")
check(f"three searches ({sent})", sent.count("search s") == 3)
sent.clear()
waiting = b._search_gate(pre, "S", R)
check(f"…then a look to check the room, not giving up ({sent})", waiting and sent == [""] and "ROUND" not in sent)
check("…waits for the room to show", b._search_gate(pre, "S", R) and sent == [""])
g.view_seq += 1                                 # the room came back: still 1/1070
sent.clear()
b._search_gate(pre, "S", R)
check(f"same room, still hidden → searches again ({sent})", sent == ["search s"])
for _ in range(16):
    b._search_line("You notice nothing different to the south.")
    b._search_gate(pre, "S", R)
check(f"…up to 20 searches (Dan, 2026-11-02: 'the exit is there') ({sent.count('search s') + 3})",
      sent.count("search s") + 3 == 20 and "ROUND" not in sent)
b._search_line("You notice nothing different to the south.")
b._search_gate(pre, "S", R)
check("…then goes round", sent[-1] == "ROUND")
# found it on the 5th
sent.clear(); b._search_wait = None
b._search_gate(pre, "S", R)
for _ in range(2):
    b._search_line("You notice nothing different to the south.")
    b._search_gate(pre, "S", R)
b._search_line("You notice nothing different to the south.")
b._search_gate(pre, "S", R)
g.view_seq += 1
b._search_gate(pre, "S", R)
b._search_line("You found an exit to the south!")
check("found on the 4th → move", not b._search_gate(pre, "S", R))
# Dan, 2026-11-02: the party searches too ('@party search north' — Buddy's a half-ogre)
from mudpilot.gamestate import RoomView
import time as _t
g.party = {"Kang": {}, "Evolution": {}, "Revolution": {}}
s.partysync.peers = {"Evolution": {"t": _t.time()}, "Revolution": {"t": _t.time()}}
g.view = RoomView("Crypt, Small Chamber", {"N"}, [], [], ["Evolution", "Revolution"], _t.time())
sent.clear(); b._search_wait = None
b._search_gate(pre, "S", R)
for _ in range(2):
    b._search_line("You notice nothing different to the south.")
    b._search_gate(pre, "S", R)
b._search_line("You notice nothing different to the south.")
b._search_gate(pre, "S", R)                   # the look
g.view_seq += 1
b._search_gate(pre, "S", R)
asks = [c for c in sent if "@do" in c]
check(f"after 3 misses the party searches too ({asks})",
      len(asks) == 2 and all(c.endswith("search s^Msearch s^Msearch s^Msearch s") for c in asks))
b._search_line("Evolution found an exit to the south!")
check("one of them finds it → move", not b._search_gate(pre, "S", R))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
