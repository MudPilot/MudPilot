"""Dan, 2026-10-30: sleep (slep) is a partial-round spell — cast early in the round it wears off before the round
goes and does nothing. Cast it in the last 2 s of the round."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st)
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


b, g, clock = s.bot, s.state, s.clock
clock.period, clock.learned = 5.0, True
s.spellbook.find = lambda w: {"Name": "Sleep", "Number": 1} if w.lower() == "slep" else \
    ({"Name": "Magic missile", "Number": 2} if w.lower() == "mmis" else None)
g.view = RoomView("Town Gates", {"N"}, [], [], [], time.time())
g.known_spells = ["slep", "mmis"]          # (0.8.201: a command is a cast only if it is one of our spells)


def round_ago(secs):
    clock.last_round = clock.last_line = time.time() - secs


round_ago(0.5)
b.send("slep orc")
check(f"early in the round: held ({sent})", not sent and b._late_q)
b._late_flush()
check("…still held 4.5 s before the round", not sent)
round_ago(3.3)
b._late_flush()
check(f"last 2 s: cast ({sent})", sent == ["slep orc"] and not b._late_q)
sent.clear(); round_ago(0.5)
b.send("mmis orc")
check(f"other spells go at once ({sent})", sent == ["mmis orc"])
sent.clear(); round_ago(3.5)
b.send("slep orc")
check(f"already late: straight away ({sent})", sent == ["slep orc"])
sent.clear(); clock.last_round = 0
b.send("slep orc")
check(f"no round seen yet: straight away ({sent})", sent == ["slep orc"])
sent.clear(); round_ago(0.5); b.send("slep orc"); b._late_q = (b._late_q[0], time.time() - 9); b._late_flush()
check("held too long (moved on): dropped", not sent and not b._late_q)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
