"""Running only uses exits the room shows, and tries another at once if one fails."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.say_panic = False
s = Session(st); b = s.bot
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T(); s._want_connected = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
s.state.candidates = []      # room unknown (mis-located): only the shown exits count
s.state.view = RoomView("Main Road", {"N", "S", "E", "W"})
b.flee()
first = sent[-1]
check(f"runs through a shown exit ({first})", first in ("n", "s", "e", "w"))
b.note_line("There is no exit in that direction!")
check(f"tries a different exit straight away ({sent})", len(sent) >= 2 and sent[-1] != first and sent[-1] in ("n", "s", "e", "w"))
s.state.view = RoomView("Dead end", {"S"})
sent.clear(); b.flee()
check("one exit → that one", sent == ["s"])
sent.clear(); b.note_line("There is no exit in that direction!")
check("nothing left to try → stops trying", sent == [])
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
