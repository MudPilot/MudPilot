"""Comeback without an @where answer (MegaMUD in the dark): walk back to where we last saw them, then along our
trail, and invite them when they're there."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.party_comeback = True
s = Session(st)
sent, gotos = [], []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T()
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
cb, g, b = s.comeback, s.state, s.bot
b.goto = lambda room, then=None: gotos.append(tuple(room)) or True
A, B, C, D = (1, 10), (1, 11), (1, 12), (1, 13)
cb._last_members = ["Miserable", "Revolution"]
g.party = {"Miserable": {}, "Revolution": {}}
# walking A → B → C with Revolution along; he was last seen with us in B
g.history.extend([A, B])
g.candidates = [B]
g.view = RoomView("Trail", {"E"}, [], [], ["Revolution"], time.time())
cb.tick()
g.history.append(C)
g.candidates = [C]
g.view = RoomView("Trail", {"E"}, [], [], [], time.time())
g.party = {"Miserable": {}}
cb.missing = {"Revolution": {"why": "dropped", "t": time.time()}}
cb.fetch = {"name": "Revolution", "phase": "asked", "room": None, "back": None, "t": time.time() - 11}
b.walking = False
cb.tick()
check(f"no @where answer: back to where we last saw him ({gotos})", gotos == [B])
# not there: the next room back along the trail
g.candidates = [B]
g.view = RoomView("Trail", {"E"}, [], [], [], time.time())
cb.tick()
check(f"not there: the room before it on our trail ({gotos})", gotos == [B, A])
# found him in A: invite
g.candidates = [A]
g.view = RoomView("Trail", {"E"}, [], [], ["Revolution"], time.time())
sent.clear()
cb.tick(); cb.tick()
check(f"found: invited ({sent})", any(c == "invite Revolution" for c in sent))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
