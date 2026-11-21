"""Dan, 2026-11-07: the Search switch is for hidden gold and items — search each room once, not only rooms with a
hidden exit (hidden exits on the way are searched by the walker whatever the switch says)."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
b, g, w = s.bot, s.state, s.world
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


plain = next(k for k, r in w.rooms.items() if not any(e.kind == "hidden" for e in r.exits.values()))
st.auto_search = True
g.candidates = [plain]
g.view = RoomView("Trail", {"N"}, [], [], [], time.time())
b.misc_tick()
check(f"a room with no hidden exit is searched too ({sent})", sent[:2] == ["search", ""])
sent.clear(); b._cool.pop("search", None); b.misc_tick()
check(f"…once ({sent})", "search" not in sent)
st.auto_search = False
g.candidates = [next(k for k in w.rooms if k != plain)]
sent.clear(); b.misc_tick()
check("switch off: no room searches", "search" not in sent)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
