"""0.8.45: the only way in failed once (a hidden exit whose push missed) — Go to still gets you there."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
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
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
w = s.world
s.state.candidates = [(12, 1811)]; s.state.level = 47; s.state.carrying = "nothing"
ex = w.rooms[(12, 1811)].exits["N"]
first = ex.action_cmds()[0]
w.fail_edge((12, 1811), "N")
check("a failed push rotates to the next wording", ex.action_cmds()[0] != first)
check("Go to the pyramid's second level still plans (the failed exit is the only way)", s.bot.goto((12, 2002)))

# the push is done in another room: 'push block' in 12/1808 opens 12/1811's north wall
from mudpilot.megamud_files import path_from_route
w.failed_edges.clear()
ex.actions[0]["cmds"] = ["push block", "push square block", "move block"]
check("MME says where the block is pushed (12/1808)", w.action_at(ex) == (12, 1808))
r = w.route((12, 1811), (12, 2002), level=47)
mp = path_from_route(w, (12, 1811), r)
pushes = [(st_.room, st_.pre) for st_ in mp.steps if "push block" in (st_.pre or [])]
check("the path walks to 12/1808 and pushes the block there", pushes and pushes[0][0] == (12, 1808))
k = next(i for i, x in enumerate(mp.steps) if x.room == (12, 1811) and x.move == "N")
check("…then comes back to 12/1811 and goes north (without pushing in the wrong room)",
      k > 0 and not mp.steps[k].pre and mp.steps[k].dest == (12, 1819))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
