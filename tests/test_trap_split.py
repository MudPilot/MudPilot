"""Pyramid, 2026-10-28: 'push block', then a trap two rooms on ('…and vanish!', a fall down a shaft) split the
party. It asked Revolution to '@do push block', waited 30 s and walked back up without him. Now: @where him."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.party_comeback = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g.candidates = [(12, 1906)]
g.view = RoomView("Great Pyramid", {"N", "W"}, [], [], ["Revolution"], time.time()); g.view_seq += 1
t0 = time.time()
b._bring = {"dest": (12, 1906), "names": ["Revolution"], "t": t0, "from": (12, 1905), "cmd": "push block", "said": False}
b.note_line("You are surrounded by a shimmering blue light, and vanish!")
b.x._party_broke_at = time.time()
g.candidates = [(12, 1263)]
g.view = RoomView("Scorched Cavern, Firepit", {"NW", "SW"}, [], [], [], time.time()); g.view_seq += 1
r = b._waiting_for_party_through(time.time())
check(f"trap split: holds and asks @where ({sent})", r and "/Revolution @where" in sent
      and not any("@do push block" in c for c in sent))
check("comeback has him as missing", "Revolution" in s.comeback.missing and s.comeback.fetch)
# no trap, but they never came through: after 30 s go get them, don't walk on
s.comeback.reset(); sent.clear()
b._bring = {"dest": (12, 1906), "names": ["Revolution"], "t": time.time() - 31, "from": (12, 1905),
            "cmd": "push block", "said": False, "broke": True, "pulled": time.time() - 31}
b._flung_at = 0
r = b._waiting_for_party_through(time.time())
check(f"30 s and no show: @where, not carrying on ({sent})", r and "/Revolution @where" in sent)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
