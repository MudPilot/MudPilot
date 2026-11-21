"""Loop stats per lap; safe-room resting; smart sneak."""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, loopstats
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route
from mudpilot.gamestate import RoomView
tmp = tempfile.mkdtemp()
loopstats.LoopStats.path = lambda self: os.path.join(tmp, "loop_stats.json")
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st); b = s.bot; w = s.world
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
lp = path_from_route(w, (1, 3), w.route((1, 3), (1, 16)) + w.route((1, 16), (1, 3)), name="Loop A")
lp.filename = "/x/LOOPA.mp"
s.state.candidates = [(1, 3)]
b.start_path(lp, loop=True, checked=True)
check("lap waits for the first on-loop step", s.loopstats._lap is None and b._loop_reset_pending is lp)
b._begin_loop(lp)
ls = s.loopstats
ls._lap["t"] -= 600
s.state.exp_gained += 300000; s.state.kills += 40
b.laps = 1; ls.lap_end(lp)
sm = ls.summary("loopa.mp")
check(f"lap recorded: ~1.8M/hr ({sm and round(sm['exp_hr'])})", sm and 1_700_000 < sm["exp_hr"] < 1_900_000)
check("next lap started", ls._lap and ls._lap["key"] == "loopa.mp")
# safe rest: pretend current room is a lair and the next step isn't
lair = next(k for k, r in w.rooms.items() if r.lair)
calm = next(k for k, r in w.rooms.items() if not r.lair and r.exits)
class St: pass
s.state.candidates = [lair]
b.path.steps[b.idx].dest = calm
st.rest_below_hp = 75; s.state.max_hp = 600; s.state.hp = 400
check("lair room → rest a step on", b._rest_elsewhere([]))
s.state.hp = 150
check("badly hurt → rest right here", not b._rest_elsewhere([]))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
