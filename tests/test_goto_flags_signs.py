"""Evolution, 2026-11-05 (report-20261105-191735): asked the Grey Lord 'box' (NeutralQuest 4 -> 5 in the game), then a
Go to to Chancellor Annora said "No walkable route ... next step: talk to The Grey Lord about 'box'". MudPilot did read
'abil' again, and the game answered 5, but:
- the answer was only taken in from a room with no monsters and no items - Town Square has 'small sign, large sign',
  so it was never saved and every later Go to planned with 4;
- the parked Go to re-planned 3 s after 'abil' went out, before the answer counted (4 s).
Now the answer is taken in every tick wherever you stand, and the parked Go to waits for it (10 s at most)."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
out, logs = [], []
class T:
    connected = True
    def send_line(self, x): out.append(x)
s.telnet = T()
b.log = lambda m, *a, **k: logs.append(m)
s.log = b.log
replans = []
b.replan = lambda target, then=None, ask=None, **k: replans.append((target, st.known_abils.get("127")))

class View:
    monsters = []
    items = ["small sign", "large sign"]          # Town Square
g.view = View()
g.candidates = [(1, 224)]
st.known_abils = {"127": 4}
g.abil_names[127] = "NeutralQuest"

def tick():
    try:
        b.tick()
    except Exception as e:                        # the rest of the tick isn't what's tested here
        logs.append(f"tick: {e!r}")

# the Go to parked for 'abil' (what _reread_flags + goto do)
t0 = time.time()
b._abil_read = ("sent", t0)
b._pending_abil = ((1, 1333), None, None, t0)
# the answer arrives (rows stamped after the send): NeutralQuest 5
g.abil_rows[("granted", 127)] = (5, t0 + 0.5)
g.abil_rows[("granted", 134)] = (12, t0 + 0.5)

# 3.5 s in: the answer isn't counted yet - the Go to must not re-plan with the old 4
b._abil_read = ("sent", time.time() - 3.5)
b._pending_abil = ((1, 1333), None, None, time.time() - 3.5)
g.abil_rows[("granted", 127)] = (5, b._abil_read[1] + 0.5)
g.abil_rows[("granted", 134)] = (12, b._abil_read[1] + 0.5)
tick()
check(f"3.5 s after 'abil', answer not in yet: doesn't re-plan with the old flags ({replans})", not replans)

# 5 s in, standing by the signs: the answer is taken in, then the Go to re-plans with 5
b._abil_read = ("sent", time.time() - 5)
b._pending_abil = ((1, 1333), None, None, time.time() - 5)
g.abil_rows[("granted", 127)] = (5, b._abil_read[1] + 0.5)
g.abil_rows[("granted", 134)] = (12, b._abil_read[1] + 0.5)
tick()
check(f"items in the room (signs): the answer still counts - NeutralQuest now {st.known_abils.get('127')}",
      st.known_abils.get("127") == 5)
check(f"...and the parked Go to re-plans with 5 ({replans})", replans and replans[0] == ((1, 1333), 5))
check("...and says the flag went up", any("New quest flag" in m and "= 5" in m for m in logs))

# no answer at all: gives up waiting after 10 s and re-plans anyway (doesn't hang)
replans.clear()
b._abil_read = ("sent", time.time() - 11)
g.abil_rows.clear()
b._pending_abil = ((1, 1333), None, None, time.time() - 11)
b._abil_read = ("sent", time.time() - 3.9)     # (a fresh periodic read going out doesn't hold it forever)
b._pending_abil = ((1, 1333), None, None, time.time() - 11)
tick()
check(f"no answer within 10 s: re-plans anyway ({replans})", replans)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
