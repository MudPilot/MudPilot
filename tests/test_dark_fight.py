"""Dan, 2026-10-28: Buddy in a dark room while the party fought a dark-elf sentry — "Revolution moves to attack tall
dark-elf sentry.", "The tall dark-elf sentry swings at Revolution…" — and it stood there: it can't see the room, so
it never saw the monster. A monster that attacks you / the party, or that a member moves to attack, is fought."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"; st.auto_combat = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g, b = s.state, s.bot
g.party = {"Revolution": {}, "Evolution": {}, "Buddy": {}}
g.candidates = [(8, 470)]
def line(t):
    g.feed_line([(t, None)])
line("The room is very dark - you can't see anything")
line("The sentry insults you with his dying breath.")
check("a death line doesn't add a monster", not (g.view and g.view.monsters))
line("Revolution moves to attack tall dark-elf sentry.")
check(f"party member attacks something we can't see → it's in the room ({g.view and g.view.monsters})",
      g.view and any(sh == "tall dark-elf sentry" for sh, _r in g.view.monsters))
line("The angry dark-elf sentry swings at you with their falchion!")
check(f"…and one swinging at us ({[sh for sh, _r in g.view.monsters]})",
      any(sh == "angry dark-elf sentry" for sh, _r in g.view.monsters))
line("The door slams shut on Revolution!")
check("not a monster: ignored", len(g.view.monsters) == 2)
line("The orc swings at Somebody with a club!")
check("someone outside the party: ignored", len(g.view.monsters) == 2)
sent.clear()
for _ in range(12):
    b.tick()
    time.sleep(0.3)
check(f"…and it fights ({sent[:8]})", any("sentry" in c for c in sent))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
