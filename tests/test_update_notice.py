"""0.8.201 (Dan): before rollout.py restarts a party, the leader telepaths the party that an update is coming, so a
player at the keys (Revolution's) knows."""
import os, sys, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, control
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st); s._no_log_file = True
sent, banners = [], []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True
s.on_banner = lambda text, kind: banners.append(text)
s.state.party = {"Miserable": {}, "Revolution": {}}
cb = s.control
d = tempfile.mkdtemp()
cb._p = lambda name: os.path.join(d, name)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
cb._update_notice()
check("nothing asked: nothing said", not sent)
open(os.path.join(d, "update-soon"), "w").close()
cb._update_notice()
check(f"telepathed the party ({sent})", sent == [f"/Revolution {control.ControlBox.UPDATE_NOTICE}"])
check("braces: no MudPilot reads it as a command", control.ControlBox.UPDATE_NOTICE.startswith("{"))
check("shown here too", banners)
check("asked once: file gone", not os.path.exists(os.path.join(d, "update-soon")))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
