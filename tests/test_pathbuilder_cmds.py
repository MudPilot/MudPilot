"""Path builder: your own commands in a path or loop (Dan, 2026-10-28: a treasure-digging loop in 13/211)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from types import SimpleNamespace as NS
from mudpilot.worlddb import WorldDB
from mudpilot.pathbuilder import PathBuilder
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
w = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"))
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
start = (13, 211)
r = w.room(start)
d, ex = next((d, e) for d, e in r.exits.items() if e.kind == "normal" and e.to in w.rooms)
back = w.room(ex.to).exits.get({"N": "S", "S": "N", "E": "W", "W": "E", "NE": "SW", "SW": "NE", "NW": "SE",
                                "SE": "NW", "U": "D", "D": "U"}[d])
pb = NS(start=start, route=["dig", ex, back], s=NS(world=w), name=NS(get=lambda: "Treasure Digging"))
for f in ("exits", "here", "is_loop", "_here_at"):
    setattr(pb, f, getattr(PathBuilder, f).__get__(pb))
mp = PathBuilder.build(pb)
check(f"dig, step out and back: a loop ({[s.to_line() for s in mp.steps]})", mp.is_loop and len(mp.steps) == 2)
check("'dig' goes before the first move", mp.steps[0].pre[:1] == ["dig"])
pb.route = [ex, back, "dig", "search"]
mp = PathBuilder.build(pb)
check(f"commands at the end of a loop go before the first step ({mp.steps[0].pre})", mp.steps[0].pre[:2] == ["dig", "search"])
pb.route = [ex, "dig", back]
mp = PathBuilder.build(pb)
check(f"…in the middle: before the move out of that room ({mp.steps[1].pre})", mp.steps[1].pre[:1] == ["dig"]
      and not mp.steps[0].pre)
# only commands: a loop that stays put and repeats them (dig at 430% encumbrance — no walking)
pb.route = ["dig"]
mp = PathBuilder.build(pb)
check(f"dig only: a one-room loop ({[s.to_line() for s in mp.steps]})", mp.is_loop and len(mp.steps) == 1
      and mp.steps[0].move == "" and mp.steps[0].pre == ["dig"])
import tempfile
from mudpilot.megamud_files import write_mp, read_mp
fn = os.path.join(tempfile.mkdtemp(), "dig.mp")
write_mp(mp, fn)
back_ = read_mp(fn)
check(f"…survives save + load ({[s.to_line() for s in back_.steps]})", back_.steps[0].move == "" and back_.steps[0].pre == ["dig"])
import time
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s_ = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s_._no_log_file = True
sent = []
s_.send = lambda c, from_bot=False: sent.append(c)
bot = s_.bot
bot._swap = None
bot.idx = 0
t0 = time.time()
bot._stay_step(mp.steps[0], t0)
check(f"stay step sends dig ({sent})", sent == ["dig"] and bot.idx == 0)
bot._stay_step(mp.steps[0], t0 + 1)
check("…waits for the answer", bot.idx == 0 and sent == ["dig"])
s_.state.last_prompt = t0 + 3
bot._stay_step(mp.steps[0], t0 + 3)
check("…then on to the next lap", bot.idx == 1)
bot.idx = 0
bot._stay_step(mp.steps[0], t0 + 3.1)
check(f"…and digs again ({sent})", sent == ["dig", "dig"])
# dig drops you in a Dark Pit (13/315-323): get back ('climb out'), then dig again — never dig in the pit
from mudpilot.gamestate import RoomView
s_.telnet.sock = object(); s_._connected_at = time.time() - 60
def at(k, name, ex):
    s_.state.candidates = [k]; s_.state.view = RoomView(name, ex, [], [], [], time.time()); s_.state.view_seq += 1
at((13, 211), "Jungle Trail, Lagoon", {"N", "E", "W"})
bot._stay_sent = None
bot.start_path(mp, loop=True)
at((13, 317), "Dark Pit", set())
sent.clear()
for i in range(20):
    s_.state.last_prompt = time.time(); s_.state.hp, s_.state.max_hp, s_.state.ma, s_.state.max_ma = 800, 800, 500, 500
    if "climb out" in sent and s_.state.candidates == [(13, 317)]:
        at((13, 211), "Jungle Trail, Lagoon", {"N", "E", "W"})
    bot.tick(); time.sleep(0.3)
moves = [c for c in sent if c not in ("par", "stat", "spells", "abil", "")]
check(f"fell in a pit: climbs out, then digs again ({moves})", moves[:1] == ["climb out"] and "dig" in moves[1:])
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
