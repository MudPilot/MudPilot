"""0.8.208 (Dan, 2026-11-19): after a disband, a member's own '@invite' / '@do invite' goes out — Revolution's blocked
auto-invite had filled the repeat filter and the '@invite' was dropped, then '@do invite' hit the disband pause.
And Buddy: 'join Miserable' before the invite ("You must be invited first!") — the invite a second later still joins."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.gamestate import RoomView
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st); s._no_log_file = True
out = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): out.append(x)
    def close(self): self.connected = False
s.telnet = T()
s.state.view = RoomView("Bristlewood Grove", {"E"}, players=["Miserable"])
s.send("disband party")                                  # Dan's disband (typed / @do)
s.send("invite Miserable", from_bot=True)                # the bot's own auto-invite: paused
check(f"auto-invite paused after the disband ({out})", not any(o.startswith("invite") for o in out))
s.bot.x._following = None
s._rejoin = {"leader": "Miserable"}                      # we'd followed Miserable for 3 s
out.clear(); r = s.remote.c_invite("Miserable", "")
check(f"'@invite' from Miserable 4 s later: invites ({out}, {r})", "invite Miserable" in out)
out.clear()
s.remote._in_do = True
try:
    s.send("invite miserable", from_bot=True)
finally:
    s.remote._in_do = False
check(f"'@do invite miserable': invites ({out})", "invite miserable" in out)
out.clear(); s.remote._joined = {}
s.remote.c_join("Miserable", "")
check(f"0.8.224 (Dan): an @join inside the 5-minute pause after the disband: not joined ({out})", "join Miserable" not in out)
# Buddy (who didn't disband)
s._party_hold_until = 0
out.clear(); s.remote._joined = {}
s.remote.c_join("Miserable", "")
check(f"first join goes out ({out})", "join Miserable" in out)
s._disband_then_join("You must be invited first!")
out.clear(); s.remote.c_join("Miserable", "")
check(f"…refused, then their invite: joins again ({out})", "join Miserable" in out)
out.clear(); s.remote.c_join("Miserable", "")
check(f"…but their @join right after a real join: not again ({out})", "join Miserable" not in out)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
