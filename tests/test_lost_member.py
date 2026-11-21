"""Dan, 2026-10-30: Evolution dropped out of the party; Revolution asked @where ('8/847' — a look-alike courtyard,
he was really at 8/16), went there, invited nobody, and after 20 s 'carrying on to 1/297' — walked off without him.
Now: not back after the invite → ask @where again (3 times), then stop and wait. And @where in a look-alike room
checks the board's room number before answering."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object(); s._connected_at = time.time() - 60
b, g, cb = s.bot, s.state, s.comeback
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


g.candidates = [(8, 847)]
g.view = RoomView("Hilltop Fortress, Courtyard", {"N"}, [], [], [], time.time())
g.party = {"Revolution": {}, "Buddy": {}}
cb.fetch = {"name": "Evolution", "phase": "invited", "room": (8, 847), "back": ("goto", (1, 297)),
            "t": time.time() - 25}
b.goto = lambda *a, **k: sent.append(("GOTO", a)) or True
sent.clear(); cb.tick()
check(f"not back after the invite: asks @where again, doesn't carry on ({sent})",
      "/Evolution @where" in sent and not any(isinstance(x, tuple) for x in sent))
check("…keeps the trip to carry on with later", cb.fetch and cb.fetch.get("back") == ("goto", (1, 297)))
for _ in range(3):
    cb.fetch.update(phase="invited", t=time.time() - 25)
    sent.clear(); cb.tick()
check(f"after 3 more tries: stopped and waiting, not walking off ({b.status})",
      b.status.startswith("Stopped: lost Evolution") and not any(isinstance(x, tuple) for x in sent))
# @where from a look-alike room: check first
g.located = None
s.remote._channel = "telepath"
sent.clear()
first = s.remote.c_where("Revolution", "")
check(f"@where in a look-alike room checks with the board first ({first!r}, {sent})",
      first is None and any(c.strip().lower() == (st.locate_cmd or "pro").strip().lower() for c in sent if isinstance(c, str)))
g.locate_ok += 1
sent.clear(); s.remote.tick()
check(f"…then answers ({sent})", any("map 8 room 847" in c for c in sent if isinstance(c, str)))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
