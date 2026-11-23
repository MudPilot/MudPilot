"""loops hunt: after an intentional disband, the party is re-formed by hand (typed invite) - are stragglers
still fetched / @comeback answered during the rest of the 5-minute pause?"""
import os, sys, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from mudpilot import config
from mudpilot.gamestate import RoomView
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"; st.party_comeback = True
s = Session(st); s._no_log_file = True
out = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): out.append(x)
    def close(self): self.connected = False
s.telnet = T()
s.state.view = RoomView("Bristlewood Grove", {"E"}, players=["Buddy"])
s.state.candidates = [(1, 1)]
s.send("disband party")                 # Dan's own disband
s.send("invite Buddy")                  # ...and he re-forms the party by hand right away
check(f"typed invite goes out ({out})", "invite Buddy" in out)
s.state.party = {"Revolution": {}, "Buddy": {}}
s.bot.x._own_party = True
# 60 s later, walking: Buddy got left behind and sends @comeback from another room
s._party_hold_until -= 60; s.comeback._self_left -= 60
s.state.view = RoomView("Bristlewood Grove", {"E"}, players=[])
out.clear()
r = s.remote.c_comeback("Buddy", "1/2")
check(f"re-formed party: Buddy's @comeback 60 s after the disband is answered (r={r!r})", r is not None)
s.bot.walking = True
s.comeback.fetch = None; s.comeback.missing = {}
s.comeback.feed_line("Buddy is no longer following you.")
check(f"re-formed party: a member who stops following is fetched (missing={s.comeback.missing})",
      "Buddy" in s.comeback.missing)
out.clear()
s.send("invite Buddy", from_bot=True)
check(f"re-formed party: the bot's own re-invite of Buddy goes out ({out})", any(o.startswith("invite") for o in out))
print("ALL PASS" if ok else "SOME FAILED")
