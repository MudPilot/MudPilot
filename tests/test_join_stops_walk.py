"""Joining someone's party ('You are now following Revolution.') stops our own Go to / loop, and while following,
Rego and their @rego don't send us off on a trip of our own."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import MPath
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st)
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
b = s.bot
trip = MPath(name="Go to 1/1813 Pier", author="", start_hash="a", end_hash="b")
b.path, b.walking, b.loop = trip, True, False
b.x.note_line("You are now following Revolution.")
check("joining stops our own walk", not b.walking)
check("…and leaves nothing for Rego", not getattr(b, "resume", None))
b.resume = {"path": trip, "loop": False, "after": None, "target": (1, 1813)}
check("Rego while following doesn't start our trip", not b.rego() and not b.walking)
b.resume = {"path": trip, "loop": False, "after": None, "target": (1, 1813)}
b.last_path, b.last_loop = trip, True
out = s.remote.c_rego("Revolution", "")
check(f"their @rego doesn't either ({out})", "following Revolution" in out and not b.walking)
b.x.note_line("You are no longer following Revolution.")
check("not following any more: nothing blocks Rego", getattr(b.x, "_following", None) is None)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
