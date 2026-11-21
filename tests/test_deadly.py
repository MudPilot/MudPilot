"""0.8.62: the underwater passage drowns you — never stand still in it: no pro, no rest, no holds; drowning
while stopped → get out."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
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
b, g = s.bot, s.state
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
feed("[HP=684/MA=473]:Muddy Underwater Passage", "Obvious exits: north, south")
g.candidates = [(12, 124)]
check("the underwater passage is a deadly room", b.in_deadly())
b._locate_at = 0
check("no 'pro' there", not b.locate_now("x") and "pro" not in sent)
g.max_hp, g.hp = 684, 400
check("no resting there", not b.should_rest([], False))
b.hold("member down", "Revolution is held")
check("no hold keeps you there", "member down" not in b.walk_holds())
b.release("member down")
g.history = [(12, 123), (12, 124)]
sent.clear()
feed("You are drowning!")
check(f"drowning while stopped: back the way we came ({sent})", "s" in sent)
st.deadly_rooms = []
feed("[HP=684/MA=473]:Muddy Underwater Passage", "Obvious exits: north, south")
feed("You are drowning!")
check("…and a room that drowns you is learned", "Muddy Underwater Passage" in st.deadly_rooms)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
