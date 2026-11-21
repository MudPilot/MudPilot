"""Dan, 2026-11-10: Go to from Rocky Trail to the Iron House — 'Can't route: current room unknown. Press Enter to look
first.' and nothing went. Now Go to looks (asks the board where it can) and goes once the room's known."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Dan"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()
sent, logs, replans = [], [], []
b, g = s.bot, s.state
b.send = lambda c, *a, **k: sent.append(c)
b.log = lambda m, *a, **k: logs.append(m)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

g.candidates = []
r = b.goto((6, 569))
check(f"room unknown: Go to doesn't give up ({r})", r is True)
check(f"…it looks / asks the board ({sent})", sent and sent[-1] in ("", (st.locate_cmd or "").strip()))
check("…and says what it's doing", any("finding out which room" in m for m in logs))
real_replan = b.replan
b.replan = lambda *a, **k: replans.append((a, k))
b.tick()
check("room still unknown a moment later: waits", not replans and b._goto_retry)
g.candidates = [(10, 305)]
b.tick()
check(f"room known: goes ({replans})", replans and replans[0][0][0] == (6, 569) and replans[0][1].get("looked"))
check("…once", not b._goto_retry)
# never known: after 15 s it tries once more, and that one says so instead of looking forever
replans.clear(); g.candidates = []; sent.clear(); logs.clear()
b.goto((6, 569))
b._goto_retry["t"] = time.time() - 16
b.tick()
check("15 s and still unknown: one last try", len(replans) == 1)
logs.clear(); sent.clear()
r = b.goto((6, 569), _looked=True)
check(f"…which gives up and says so ({logs})", r is False and any("still can't tell" in m for m in logs)
      and not getattr(b, "_goto_retry", None))
# a walk you start meanwhile wins
b.walk = lambda *a, **k: None
b.goto((6, 569)); b.walking = True; replans.clear(); g.candidates = [(10, 305)]; b.tick()
check("a walk started meanwhile: no Go to on top of it", not replans and not b._goto_retry)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
