"""Dan, 2026-11-01: Buddy's Go to to the Tree House (1/2305) went through the Slum Street Rusted Gate (1/1169 E —
'[1000 picklocks/strength]', nobody picks or bashes it) and sent 'e' into "The gate is closed!" about 80 times.
A door nothing opens isn't a route when there's another way, and a closed door is never walked into: 'open' it."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.megamud_files import Step
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


g, b, w = s.state, s.bot, s.world
gate = (1, 1169)
ex = w.room(gate).exits["E"]
for a in ((1, 1167), (1, 1169)):
    r = w.route(a, (1, 2305))
    check(f"{a[0]}/{a[1]} → Tree House goes round the gate ({len(r or [])} steps)",
          r and not any(e.to == ex.to and e.dir == "E" for e in r))
# an old path / no other way: at the gate, closed → 'open east', never 'e'
g.candidates = [gate]
g.strength, g.picklocks, g.max_hp, g.hp = 70, 0, 286, 286
g.view = RoomView("Slum Street, Rusted Gate", {"N", "S", "E"}, [], [], [], time.time(), closed={"E"})
b.walking, b.path = True, type("P", (), {"steps": [Step("E", 0, "E", [], gate, ex.to)], "title": "old path",
                                         "is_loop": False, "filename": "", "needed_item": ""})()
b.idx, b._lock_tries, b._unlocked = 0, {}, None
sent.clear(); b._cool.clear()
for _ in range(12):
    b._door_wait_until = 0; b._timed_retry_at = 0
    try:
        b.walk([], True)
    except Exception:
        pass
    g.pending.clear()
moves = [c for c in sent if c.lower() in ("e", "east")]
opens = [c for c in sent if c.startswith("open")]
check(f"never walks into the closed gate ({moves})", not moves)
check(f"…tries to open it instead ({opens[:3]})", opens and opens[0] == "open east")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
