"""Following a MegaMUD leader: @wait when we rest/meditate, @ok when topped up (or if we stop resting)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
st.auto_rest = True; st.rest_below_hp, st.rest_until_hp = 75, 85; st.rest_below_ma, st.rest_until_ma = 30, 80
st.use_meditate = True; st.auto_combat = False; st.auto_bless = False; st.auto_spells = False
s = Session(st); b = s.bot
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T()
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
def tick(n=3):
    for _ in range(n):
        b._cool = {"par": time.time(), "par_solo": time.time()}; b.tick()
s.state.view = RoomView("Trail", {"N"}); s.state.view.t = time.time() + 999
s.state.max_hp, s.state.hp, s.state.max_ma, s.state.ma = 600, 590, 400, 80
s.state.party = {"Revolution": {"hp": 100, "ma": 100, "t": time.time()}, "Miserable": {"hp": 98, "ma": 20, "t": time.time()}}
b.x.note_line("You are now following Revolution.")
tick()
check(f"meditating → tells the leader @wait ({sent})", "/Revolution @wait (meditating)" in sent and any(c in ("medi", "meditate") for c in sent))
sent.clear(); s.state.resting = True; s.state.ma = 360
tick()
check(f"topped up → @ok ({sent})", "/Revolution @ok" in sent)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
