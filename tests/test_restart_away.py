"""A member @stops us and logs off for a restart: the leader stays put (no @where, no Go to after them) — they come
back to this room. Once they follow again, comeback works as usual. (2026-10-30: the PVE leader went looking for
Evolution, and Buddy came back alone through the dark elves and hung up.)"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"; st.party_comeback = True
st.remote_players = {"Evolution": ["party", "move"], "Buddy": ["party", "move"]}
s = Session(st)
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T(); s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
g, cb = s.state, s.comeback
s.bot.x._own_party = True
g.party = {"Revolution": {"hp": 100, "t": time.time()}, "Evolution": {"hp": 100, "t": time.time()},
           "Buddy": {"hp": 100, "t": time.time()}}
cb._self_left = 0
s.remote.handle("telepath", "Evolution", "@stop")
sent.clear()
feed("Evolution is no longer following you.")
check(f"restart: no @where, no chase ({sent})", not any("@where" in x for x in sent) and "Evolution" not in cb.missing
      and not cb.fetch)
feed("Evolution started to follow you.")
check("back with us: the restart mark is gone", not cb.stepped_away("Evolution"))
sent.clear()
feed("Buddy is no longer following you.")
check(f"someone who didn't @stop us is still looked for ({sent})", any("/Buddy @where" in x for x in sent))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
