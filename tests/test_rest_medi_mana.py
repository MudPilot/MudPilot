"""Miserable PVE (Dan, 2026-11-03): rests at 55% mana, up at 65%. (1) Meditating for mana with HP 83% (over his 60%
rest-below, under his 90% rest-until) he sat there till the game woke him at full — the mana's what he meditates
for. (2) At 37% mana in a lair, the quieter-room rule walked him on into three crabs: below your rest % you rest."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
st.rest_below_hp, st.rest_until_hp, st.rest_below_ma, st.rest_until_ma = 60, 90, 55, 65
st.rest_smart_full = False
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): pass
s.telnet = Tel(); s._entered = True
b, g = s.bot, s.state
b._up_on_tick = lambda: False
g.max_hp, g.max_ma = 855, 529
g.party = {}

def state(hp, ma, resting=True, medi=True):
    g.hp, g.ma, g.resting, g.meditating = hp, ma, resting, medi

state(714, 305)                       # 83% HP, 58% mana, meditating
check("meditating, mana under 65%: keeps going", b.should_rest([], False))
state(714, 447)                       # 84% mana
check("meditating, mana over 65%, HP 83%: gets up", not b.should_rest([], False))
state(714, 447, medi=False)
check("resting (not meditating): still rests HP up to 90%", b.should_rest([], False))
state(450, 447)                       # 53% HP: under rest-below
check("meditating but HP under 60%: keeps going", b.should_rest([], False))

# (2) the quieter-room rule
lair = next(k for k, r in s.world.rooms.items() if r.lair)
quiet = next(k for k, r in s.world.rooms.items() if not r.lair)
st.safe_rest_steps = 3
b.walking = True
b.path = type("P", (), {"steps": [type("S", (), {"dest": quiet})()]})()
b.idx = 0; b._fled = False
g.candidates = [lair]; g.in_combat = False
state(800, 400, resting=False, medi=False)   # 76% mana, HP 94%
g.hp = 450                                    # resting for HP (53%), mana fine
check("resting for HP with mana fine: walks on to the quieter room", b._rest_elsewhere([]))
g.ma = 196                                    # 37% mana
check("mana under the rest %: rests right here", not b._rest_elsewhere([]))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
