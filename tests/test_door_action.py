"""0.8.64: the Golden Spire library's north door opens with 'turn stand' (MME knows it) — 1000 picklocks/strength,
so never bash or pick it; and other closed doors get bashed before 'open' is even tried."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 47
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
b, w, g = s.bot, s.world, s.state
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
ex = w.rooms[(12, 2247)].exits["N"]
check(f"MME's 'turn stand' is on the library's north door ({ex.action_cmds()})", "turn stand" in ex.action_cmds())
from mudpilot.megamud_files import path_from_route
r = w.route((12, 2247), (12, 2248), level=47)
mp = path_from_route(w, (12, 2247), r, name="Go to 12/2248")
check(f"the step turns the stand first ({mp.steps[0].pre})", "turn stand" in (mp.steps[0].pre or []))
# the door's still shut: the lock flow does the stand again — never bash / pick
g.candidates = [(12, 2247)]
g.view = RoomView("Golden Spire, Library", {"N", "W"}, [], [], [], time.time(), {"N"})
b.start_path(mp, loop=False, checked=True); b._goto_target = (12, 2248)
g.candidates = [(12, 2247)]
b._lock_room = (12, 2247); b._lock_tries = {}
tried = []
for _ in range(4):
    b._locked_dir = "N"; b._door_wait_until = 0; sent.clear()
    g.pending.clear(); b._expect_seq = None
    b.walk([], False)
    tried += [x for x in sent if x]
check(f"locked: 'turn stand' / 'open north', no bash or pick ({tried})",
      tried and not any(x.startswith(("bash", "pick")) for x in tried) and "turn stand" in tried)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
