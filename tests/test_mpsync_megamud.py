"""@mpsync hi to a MegaMUD player: '{command invalid or not allowed}' → don't ask them again for a week."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.party_sync = True
s = Session(st); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
s.state.party = {"Miserable": {}, "Revolution": {}}
s.partysync.tick()
check("asks Revolution once", sent.count("/Revolution @mpsync hi tune") == 1)
s.remote.feed_line("Revolution telepaths: {command invalid or not allowed}")
check("MegaMUD's answer noted", "revolution" in st.mpsync_not)
s2 = Session(st); s2._no_log_file = True; s2.telnet = Tel(); s2._entered = True
s2.state.party = {"Miserable": {}, "Revolution": {}}
sent.clear(); s2.partysync.tick()
check("next session: not asked again", not any("@mpsync hi" in x for x in sent))
s2.partysync.command("Revolution", "hi tune")
check("…until Revolution's own MudPilot says hi", "revolution" not in st.mpsync_not)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
