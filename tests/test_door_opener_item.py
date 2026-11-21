"""0.8.189 (realm walk sweep): the Heavy Iron Gates (6/2619 south, '[301 picklocks/strength]') open with 'show signet
ring' — the room's command checks for the signet ring. MudPilot took the command as the door's opener but dropped
the ring, so a Go to walked a ringless character 944 rooms there and stood showing a ring it didn't have ("'S' from
6/2619 isn't getting anywhere"). Now the ring comes with the command: no ring, no way through; the way in with every
key lists the ring as something to fetch."""
import os, sys, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_door_item"))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda m, *a, **k: None
b, w = s.bot, s.world
ring = next(n for n, it in w.items.items() if it.get("name") == "gold signet ring")
ex = w.room((6, 2619)).exits["S"]
check(f"the gates' opener needs the signet ring ({ex.action_cmds()}, {ex.action_items()})",
      "show signet ring" in ex.action_cmds() and ring in ex.action_items())
def through(r, cur=(6, 2615)):
    for x in r or []:
        if cur == (6, 2619) and x.dir == "S":
            return True
        cur = x.to
    return False
r0 = w.route((6, 2615), (6, 2620), level=55, have={1281})
check(f"no ring: not through the gates ({len(r0) if r0 else None} rooms)", not through(r0))
r1 = w.route((6, 2615), (6, 2620), level=55, have={1281, ring})
check(f"with the ring: through them ({len(r1) if r1 else None} rooms)", r1 is not None and through(r1))
rk = w.route((6, 2615), (6, 2620), level=55, have=b.every_item())
mp = path_from_route(w, (6, 2615), rk or [], name="Go to 6/2620")
check("the way in with every key goes through the gates", through(rk))
check(f"…and the ring is on its needed-items list ({b.path_needs(mp)})", any(n == ring for n, _soft in b.path_needs(mp)))
step = next((x for x in mp.steps if x.room == (6, 2619) and x.move == "S"), None)
check(f"…and shown at the gates ({step.pre if step else None})", step is not None and "show signet ring" in step.pre)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
