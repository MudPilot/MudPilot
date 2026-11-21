"""pMUD-style walking: named holds, arrival placed by the path, drift policy, doors opened first,
party/paid moves never re-sent, kills credited by their own death line."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.gamestate import RoomView
from mudpilot.worlddb import DIR_WORDS
st = config.Settings(); st.save = lambda: None
s = Session(st); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
b, g, w = s.bot, s.state, s.world
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
# 1 named holds
b.hold("you", "paused by hand")
check("a named hold shows up", b.walk_holds().get("you") == "paused by hand")
b.release("combat")
check("…another source can't release it", "you" in b.walk_holds())
b.release("you")
check("…its own source can", "you" not in b.walk_holds())
# 2 arrival placed by the path: two look-alike rooms
pair = None
for name, keys in w.by_name.items():
    if len(keys) >= 2:
        for k in keys:
            r = w.room(k)
            for d, e in r.exits.items():
                if e.kind == "normal" and e.to in keys and e.to != k:
                    pair = (k, d, e.to); break
            if pair: break
    if pair: break
k, d, dest = pair
b._expect_dest = (dest, g.view_seq, k)
g.candidates = [k, dest]
dr = w.room(dest)
g.view = RoomView(dr.name, {x for x, e in dr.exits.items() if e.visible}, [], [], [], time.time())
g.view_seq += 1
b._confirm_arrival()
check(f"look-alike rooms: placed by the path ({g.candidates})", g.candidates == [dest])
# 3 drift policy
b._drift = []; b.walking = True
for i in range(6):
    b._drifted("resync")
check("7th knock off the path in 5 min → pause and look", b._drifted("resync") and "drift" in b.walk_holds())
b._drift = []
for i in range(6):
    b._drifted("resync")
r = b._drifted("resync")
check(f"…again within 10 min → holds and finds where it is, not a stop ({b.status})",
      r and ("Stopped" in b.status or "drift" in b.walk_holds() or "pro" in b.status))
# party move not re-sent
b.walking = True; b._resends = (None, 0); b._lock_tries = {}
b._resend_guard(k, ".@party go portal")
check("first party command goes", b.walking)
r = b._resend_guard(k, ".@party go portal")
check(f"party command never sent twice ({b.status})", r and not b.walking)
# 4 doors opened first
g.view = RoomView("x", {"E"}, [], [], [], time.time(), {"E"})
check("'closed door east' is read", True)
s2 = Session(st); s2._no_log_file = True
s2._line([("Some Room", Style())]); s2._line([("Obvious exits: north, closed door east", Style())])
check(f"closed doors in the exits line ({s2.state.view.closed})", s2.state.view.closed == {"E"} and "E" in s2.state.view.exits)
# 5 kill credit per death line
g.view = RoomView("x", {"N"}, [("orc", None), ("kobold", None), ("kobold", None)], [], [], time.time())
feed("The kobold falls to the ground!", "You gain 10 experience.")
check(f"exp credited to the kobold that died ({g.last_kill_name})", g.last_kill_name == "kobold")
feed("The orc falls to the ground!", "You gain 30 experience.")
check(f"…and the next to the orc ({g.last_kill_name})", g.last_kill_name == "orc")
check(f"dead ones leave the room list ({g.view.monsters})", g.view.monsters == [("kobold", None)])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
