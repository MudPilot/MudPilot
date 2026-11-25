"""0.8.227.2 (Dan: "why pvp miserable stopped?? he was supposed to be walking"): at 99% encumbrance a winged fiend's
arrow left him "weak and powerless" — 104%, "You are too heavy to move!". The 'st' after it listed "You feel weak and
powerless! (33s)", but the hold was dropped because 'held' isn't in that line; then every refused move counted
against the exit: round NE, SW, E, and 'Stopped: NW from 14/5290 isn't getting anywhere (8 tries)'."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent, logs = [], []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
s.log = (lambda orig: (lambda m, *a, **k: (logs.append(m), orig(m, *a, **k))))(s.log)
b, g = s.bot, s.state
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)

st.message_rules_on = True
b.x._stat_lists_effects = True
feed("The winged fiend looses an arrow, striking your vitals for 46 damage!", "You feel weak and powerless!")
c = s.msgrules.conditions.get("held")
check(f"weakness: a maybe-hold ({c})", c and c.get("tentative") and "weak and powerless" in c.get("start", ""))
s.msgrules.confirm_held("You are too heavy to move!")
check("too heavy to move: the hold is real", not s.msgrules.conditions["held"].get("tentative"))
s.msgrules.conditions["held"]["since"] -= 10
b.x.ailments["held"] = time.time() - 10
feed("Name: Miserable Revolution             Lives/CP:      8/2", "Intellect: 130    Health:  120", "Willpower: 50     Charm:   50          MagicRes:       75",
     "You are affected by a mana flux! (117s)", "You feel weak and powerless! (33s)", "You are blurred! (207s)", "")
b.x._stat_block["t"] -= 2
b.x.stat_block_tick()
check("'st' still lists the weakness: still held", "held" in s.msgrules.conditions and "held" in b.x.ailments)
check("…and nobody said it was gone", not [l for l in logs if "stat effects" in l])
feed("Name: Miserable Revolution             Lives/CP:      8/2", "Intellect: 130    Health:  120", "Willpower: 50     Charm:   50          MagicRes:       75",
     "You are affected by a mana flux! (80s)", "You are blurred! (190s)", "")
b.x._stat_block["t"] -= 2
b.x.stat_block_tick()
check("'st' without it: the hold's over", "held" not in s.msgrules.conditions)

# the walk: "too heavy to move" never counts against the exit
here_ = (14, 5290)
b._resends = (None, 0)
stopped, around = [], []
b.stop = lambda why="", *a, **k: stopped.append(why)
b.route_around = lambda *a, **k: around.append(a) or True
t0 = time.time()
for i in range(30):
    feed("You are too heavy to move!")
    b._step_sent_at = 0
    b._resend_guard(here_, "nw")
check(f"30 refused moves: not gone round ({len(around)}) nor stopped ({stopped})", not around and not stopped)
b._step_sent_at = time.time()
feed("You are too heavy to move!")
check("tried again only every few seconds", b._resend_guard(here_, "nw") is True)
b._heavy_since = time.time() - b.HEAVY_STOP_SECS - 5
feed("You are too heavy to move!")
b._resend_guard(here_, "nw")
check(f"too heavy for 3 minutes: stopped, saying why ({stopped})", stopped and "too heavy to move" in stopped[-1])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
