"""Dan, 2026-11-13: Miserable PVE was still in Evolution's party from a relog (Evolution invited it, 'join if invited')
and Dan started its own Tidepool loop. On the 0.8.190 restart it treated Evolution as its leader: '@stop' to
Evolution (the whole PVE party stood still), then walked off to Rotting Glade to rejoin them. Walking a loop of its own,
a character follows nobody: no @stop for a restart, no '@comeback' when the party breaks, no 'follow' in resume.json."""
import os, sys, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ["MUDPILOT_DATA_DIR"] = os.path.join(tempfile.gettempdir(), "mudpilot_test_own_loop")
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 60
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True
b = s.bot
b.x._following = "Evolution"                       # still in Evolution's party
s.state.party = {"Miserable": {}, "Evolution": {}}
s.state.candidates = [(13, 503)]

# not walking: Evolution is our leader, as before
b.walking, b.loop, b.path = False, False, None
check(f"standing in Evolution's party: Evolution leads ({s.control._leader()})", s.control._leader() == "Evolution")

# walking our own loop: nobody
class MP:
    title = "Tidepool (Longer)-13 503"; filename = "TFTPLOO2.mp"; is_loop = True
b.walking, b.loop, b.path = True, True, MP()
check(f"walking my own loop: no leader for a restart ({s.control._leader()})", s.control._leader() is None)

# the party breaking while we loop: no '@comeback' to Evolution
sent.clear()
s.comeback.feed_line("You are no longer following Evolution.")
check(f"party breaks while I loop: nobody asked to come back ({sent})", not any("@comeback" in c for c in sent))

# …but a real follower (not walking a loop) still asks
b.walking, b.loop, b.path = False, False, None
s.comeback._self_left = 0
sent.clear()
s.comeback.feed_line("You are no longer following Evolution.")
check(f"a follower left behind still asks its leader ({sent})", any("/Evolution @comeback" in c for c in sent))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
