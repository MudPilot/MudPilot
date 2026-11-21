"""Evolution (Dan, 2026-11-03), in the guardian golem's rooms (1/1797, behind doors he picks), @hunt crimson mist:
"you need a log raft — nobody in the party has one, and there's no known place to get one". The boatman sells them;
the source search only counted shops reachable with the keys you carry. And no cash for it: the bank first."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config, errands
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
w, b, er = s.world, s.bot, s.bot.errands
raft = w.item_names["log raft"]["num"]
s.state.candidates = [(1, 1797)]
s.state.level = 21
b.held_items = lambda: set()
src = er.source_for(raft, (3, 560))
check(f"from behind the golem's doors: the raft is sold somewhere ({src and (src['kind'], src['room'])})",
      src and src["kind"] == "shop")
# can't buy it (no cash): to the bank, and back through the item check
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
b.send = lambda c, **k: sent.append(c)
b._goto_target = (3, 560)
mp = type("P", (), {"title": "Go to 3/560 Ancient Ruin, Plaza", "steps": [], "resolved": True})()
er.active = {"todo": [{"kind": "shop", "num": raft, "room": (1, 1813), "what": "Boat Launch"}], "then": (mp, False),
             "started": time.time(), "at": time.time(), "tries": errands.SHOP_TRIES, "after": None, "target": None}
s.state.candidates = [(1, 1813)]
s.state.wealth = 0
gone = []
b.goto = lambda room, then=None, **k: gone.append(room) or True
b.ready = lambda *a, **k: True
er.tick()
t = s.trips.trip
check(f"couldn't buy it: off to the bank ({t and t['room']}, {gone})", t and t["kind"] == "withdraw" and gone)
check("…and back by a Go to the Ancient Ruin, which buys it", t and t.get("goto") == (3, 560) and t.get("recheck"))
check("not stopped", "couldn't buy" not in (b.status or ""))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
