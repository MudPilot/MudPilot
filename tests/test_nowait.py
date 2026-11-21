"""0.8.53: NoWait ignores @wait; Hands off sends nothing automatic; neither survives a restart."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
s.state.party = {"Miserable": {"hp": 100, "t": time.time()}, "Revolution": {"hp": 100, "t": time.time()}}
s.remote.c_wait("Revolution", "")
check("@wait holds normally", s.remote.holding() == "Revolution")
st.no_wait = True
check("NoWait: let go", s.remote.holding() is None)
s.remote.c_wait("Revolution", "")
check("NoWait: a new @wait is ignored", s.remote.holding() is None and "party @wait" not in s.bot.walk_holds())
st.no_wait = False
st.hands_off = True
sent.clear()
s.send("par", from_bot=True)
check("Hands off: the bot sends nothing", sent == [])
s.send("look")
check("…what you type still goes", sent == ["look"])
s.poll()
check("…and the poll still runs", True)
import tempfile, json
d = tempfile.mkdtemp(); p = os.path.join(d, "s.json")
json.dump({"no_wait": True, "hands_off": True, "settings_version": 99}, open(p, "w"))
ld = getattr(config.Settings, "load")
try:
    s2 = ld(p)
    check("neither is left on after a restart", not s2.no_wait and not s2.hands_off)
except TypeError:
    check("settings load signature", False)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
