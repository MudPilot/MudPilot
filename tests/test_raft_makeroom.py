"""Handing a party member their log raft (400 encumbrance) when they're too heavy: the game says "Evolution cannot
accept your offer." The leader asks them to @makeroom, gives again; the member buys 0 (the shop changes the coins for
bigger ones), then drops the cheapest coins till it fits, never platinum (Dan, 2026-11-03)."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config, errands
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def __init__(self): self.sent = []
    def send_line(self, x): self.sent.append(x)
    def close(self): pass
def mk(name):
    st = config.Settings(); st.save = lambda: None; st.my_name = name
    s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
    s.telnet = Tel(); s._entered = True
    return s

# ---- the leader
L = mk("Miserable")
b, er = L.bot, L.bot.errands
raft = L.world.item_names["log raft"]["num"]
shop = (1, 1813)
L.state.candidates = [shop]
er.active = {"todo": [{"kind": "shop", "num": raft, "room": shop, "for": "Evolution", "what": "the pier"}],
             "then": (None, False), "started": time.time(), "at": None, "tries": 0, "after": None, "target": None}
b.ready = lambda *a, **k: True
er.tick()
check(f"buys the raft ({L.telnet.sent[-1:]})", L.telnet.sent and L.telnet.sent[-1] == "buy log raft")
cur = er.active["todo"][0]
cur["bought"] -= 5
er.tick()
check(f"gives it ({L.telnet.sent[-1]})", L.telnet.sent[-1] == "give log raft to Evolution")
b.note_line("Evolution cannot accept your offer.")
er.tick()
check(f"refused → asks them to make room ({L.telnet.sent[-1]})", L.telnet.sent[-1] == "/Evolution @makeroom log raft")
cur["room_asked"] -= errands.ROOM_SECS + 1
er.tick(); er.tick()
check(f"…then gives again ({L.telnet.sent[-1]})", L.telnet.sent[-1] == "give log raft to Evolution")
cur["given"] -= 4
er.tick()
check("taken this time: done with it", not er.active or not er.active.get("todo"))

# refused every time: stops and says why
er.active = {"todo": [{"kind": "shop", "num": raft, "room": shop, "for": "Buddy", "what": "the pier"}],
             "then": (None, False), "started": time.time(), "at": None, "tries": 0, "after": None, "target": None}
stopped = []
b.stop = lambda why="": stopped.append(why)
for _ in range(errands.GIVE_TRIES + 1):
    c = er.active["todo"][0]
    c.setdefault("bought", time.time() - 5)
    er.tick()
    b.note_line("Buddy cannot accept your offer.")
    er.tick()
    c["room_asked"] = time.time() - errands.ROOM_SECS - 1
    er.tick()
er.tick()
check(f"still refused after {errands.GIVE_TRIES} more tries: stops ({stopped[-1:]})",
      stopped and "can't carry the log raft" in stopped[-1])

# ---- the member
M = mk("Evolution")
rm, st = M.remote, M.state
st.enc = (3700, 3840, "Heavy", 96)
st.coins = {"copper farthing": 500, "silver noble": 0, "gold crown": 3000, "platinum piece": 40}
out = rm.c_makeroom("Miserable", "log raft")
check(f"first: buy 0 at the shop, then look ({M.telnet.sent[-2:]})", M.telnet.sent[-2:] == ["buy 0 log raft", "i"])
st.enc = (3600, 3840, "Heavy", 93)          # the swap helped, not enough (240 free)
st.coins = {"copper farthing": 500, "gold crown": 0, "platinum piece": 70}
rm.inv_answer()
# 0.8.201 bug hunt: only what's short (160 → 480 coins at 3 a point), not the whole stack
check(f"still heavy: drops the copper it needs ({M.telnet.sent[-2]})", M.telnet.sent[-2] == "drop 480 copper farthings")
st.enc = (3500, 3840, "Heavy", 91)          # 340 free: still short, nothing cheap left
st.coins = {"copper farthing": 0, "gold crown": 0, "platinum piece": 70}
rm.inv_answer()
check("no copper/silver/gold left: gives up, never drops platinum",
      not any("platinum" in x for x in M.telnet.sent) and rm._room is None)
rm.c_makeroom("Miserable", "log raft")
st.enc = (3300, 3840, "Heavy", 86)
n = len(M.telnet.sent)
rm.inv_answer()
check("room enough: drops nothing", len(M.telnet.sent) == n and rm._room is None)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
