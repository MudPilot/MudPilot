"""0.8.54: in the pyramid, 'You don't see sphinx fire here' / 'There is no exit in that direction!' while walking
→ ask the board where we are (pro) instead of repeating."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.megamud_files import path_from_route
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 47
st.auto_spells = st.auto_bless = st.auto_rest = st.auto_heal = False
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
b, w, g = s.bot, s.world, s.state
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
mp = path_from_route(w, (12, 1919), w.route((12, 1919), (12, 1921), level=47), name="Go to 12/1921")
g.candidates = [(12, 1920)]
b.start_path(mp, loop=False, checked=True)
b._action_sent_at = time.time()
sent.clear()
feed("You don't see sphinx fire here.")
check(f"'You don't see sphinx fire here' after the action → pro ({sent})", "pro" in sent)
b._locate_at = 0
sent.clear()
feed("There is no exit in that direction!")
check(f"'no exit in that direction' while walking → pro ({sent})", "pro" in sent)
b._locate_at = 0; b._action_sent_at = 0
sent.clear()
feed("You don't see 81 silver nobles here.")
check("a loot miss isn't taken for it", "pro" not in sent)
# the real story: the path skipped a step and walked into 12/1830, a dead end that looks like the sphinx room
mp = path_from_route(w, (12, 1811), w.route((12, 1811), (12, 1921), level=47), name="Go to 12/1921")
g.candidates = [(12, 1811)]
b.start_path(mp, loop=False, checked=True)
b._goto_target = (12, 1921)
b.idx = 9                                  # it thinks it's further on than it is
g.candidates = [(12, 1830)]
r = w.rooms[(12, 1830)]
feed("[HP=684/MA=473]:Great Pyramid", "Obvious exits: south")
g.candidates = [(12, 1830)]
sent.clear()
for _ in range(30):
    b._last_progress = time.time(); b.tick(); g.pending.clear(); s.state.in_combat = False
    for k in list(b._cool): b._cool[k] = (time.time() if k in ("par", "stat", "spells", "abil") else 0)
    if any(x in ("s", "south") for x in sent):
        break
check(f"located at the dead end: walks back out south ({sent})", any(x in ("s", "south") for x in sent))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
