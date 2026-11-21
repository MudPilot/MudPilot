"""Leader held by @wait: meditate if mana is lower, rest if HP is lower, nothing if both full; go on @ok."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.megamud_files import path_from_route
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
st.auto_rest = True; st.use_meditate = True; st.auto_combat = False; st.auto_bless = False; st.auto_spells = False
s = Session(st); b = s.bot; w = s.world
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
lp = path_from_route(w, (1, 3), w.route((1, 3), (1, 16)) + w.route((1, 16), (1, 3)), name="L")
s.state.candidates = [(1, 3)]; s.state.view = RoomView("x", {"N"}); s.state.view.t = time.time() + 999
b.start_path(lp, loop=True, checked=True)
s.state.party = {"Miserable": {"hp": 93, "ma": 53, "t": time.time()}, "Revolution": {"hp": 100, "ma": 30, "t": time.time()}}
s.state.max_hp, s.state.hp, s.state.max_ma, s.state.ma = 684, 636, 473, 253
s.remote.holds["Revolution"] = time.time()
def tick(n=2):
    for _ in range(n):
        b._cool = {"par": time.time(), "par_solo": time.time()}; b.tick()
sent.clear(); tick()
check(f"held, mana lower → meditate ({sent})", "medi" in sent)
s.state.resting = True
del s.remote.holds["Revolution"]
sent.clear(); tick()
check(f"@ok → gets up and walks on ({sent})", any(c in ("n", "s", "e", "w", "ne", "nw", "se", "sw", "u", "d") for c in sent))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
