"""Dan, 2026-10-29: 'dtch sc' (drain HP back while poisoned) drops combat after each cast; MudPilot saw *Combat Off*
with the scorpion still there and sent 'fork scorpion', Dan cast dtch again, MudPilot sent fork again… An attack or
targeted spell you type makes that fight yours: no attacks from MudPilot until you stop (2 idle rounds with combat
off, or 4 rounds since your last attack), the monster dies / leaves, or you leave."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 30
st.auto_combat = True; st.auto_spells = True; st.auto_nuke = True
st.auto_bless = st.auto_rest = st.auto_heal = False
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []        # everything that went out
mine = []        # …of which you typed these
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g, b, w, m = s.state, s.bot, s.world, s.bot.manual
g.level, g.max_hp, g.hp, g.max_ma, g.ma = 30, 400, 300, 300, 250
g.known_spells = ["mmis", "magm", "fork", "dtch", "slep", "bles"]
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ROOM = (12, 135)
r = w.rooms[ROOM]
def room(*mobs):
    feed("[HP=300/MA=250]:" + r.name, *(["Also here: " + ", ".join(mobs) + "."] if mobs else []),
         "Obvious exits: " + ", ".join({"N": "north", "S": "south", "E": "east", "W": "west"}.get(d, d.lower())
                                       for d in r.exits if len(d) <= 2))
    g.candidates = [ROOM]
def you(cmd):
    mine.append(cmd)
    s.send(cmd)
def bot_attacks():
    return [c for c in sent if c and c not in mine and "scorpion" in c.lower()]
def ticks(n=8):
    for _ in range(n):
        g.need_refresh = False           # (the board would have answered the look by now)
        b.tick()
        time.sleep(0.05)
def elapse(secs):
    """pretend 'secs' went by since your last attack"""
    m.last_attack -= secs
    m.armed_at -= secs

room("large giant scorpion")
check(f"the room's read ({g.room}, {g.view and g.view.monsters})", g.room == ROOM and g.view and g.view.monsters)

# 1. dtch sc: the override takes it, and the game's reply names it
you("dtch sc")
feed("You reach out and touch large giant scorpion!", "*Combat Off*")
check(f"'dtch sc' arms the override on the large giant scorpion ({m.mob})", m.mob == "large giant scorpion")
sent.clear(); ticks()
room("large giant scorpion")
ticks()
check(f"…no fork/magm/a from MudPilot while you cast ({bot_attacks()})", not bot_attacks())
check(f"…and it shows ({b.status!r})", b.status.startswith("MANUAL: large giant scorpion"))
elapse(6)
room("large giant scorpion"); ticks()
check(f"6 s later, combat off: still yours ({bot_attacks()})", not bot_attacks() and m.active)
you("slep sc")
feed("You cast sleep on large giant scorpion!", "*Combat Off*")
elapse(8)
room("large giant scorpion"); ticks()
check(f"slep 8 s ago (timers started again): still yours ({bot_attacks()})", not bot_attacks() and m.active)
you("dtch sc")
feed("You reach out and touch large giant scorpion!", "*Combat Off*")
# 2. a bless (not an attack) and then two idle rounds: MudPilot takes over
elapse(4)
you("bles")
room("large giant scorpion"); ticks()
check("a bless 4 s in: still yours (one missed round is normal)", m.active and not bot_attacks())
elapse(7)
room("large giant scorpion"); ticks(12)
check(f"…11 s with combat off and no attack from you: override over ({m.mob})", not m.active)
check(f"…and MudPilot attacks the scorpion itself ({bot_attacks()})", bot_attacks())

# 3. the hard ceiling: in combat, 4 rounds since your last attack
sent.clear(); mine.clear(); b._cool.clear(); b._attack_sent_at = 0
you("a sc")
feed("*Combat Engaged*")
check("'a sc' arms it again", m.mob == "large giant scorpion")
elapse(15)
room("large giant scorpion"); g.in_combat = True; ticks()
check("15 s in combat: still yours", m.active and not bot_attacks())
elapse(6)
room("large giant scorpion"); g.in_combat = True; ticks(12)
check(f"21 s: MudPilot takes over ({b.status!r})", not m.active and not b.status.startswith("MANUAL"))

# 4. the scorpion dies → the next monster is fought as usual
sent.clear(); mine.clear(); b._cool.clear(); b._attack_sent_at = 0; g.in_combat = False
you("dtch sc")
feed("You reach out and touch large giant scorpion!", "*Combat Off*")
check("armed", m.active)
feed("The large giant scorpion collapses with a shriek.", "You gain 4000 experience.")
check("it died: override over", not m.active)
room("fierce giant scorpion")
ticks(12)
check(f"…the next one's attacked straight away ({bot_attacks()})",
      any("scorpion" in c for c in bot_attacks()))

# 5. you leave the room: over
sent.clear(); mine.clear(); b._cool.clear(); b._attack_sent_at = 0
room("large giant scorpion")
you("dtch sc")
check("armed", m.active)
r2 = w.rooms[(12, 136)]
feed("[HP=300/MA=250]:" + r2.name, "Obvious exits: north"); g.candidates = [(12, 136)]
ticks(1)
check("you walked out: override over", not m.active)

# 6. not attacks: a spell at a player, a look, a target that isn't here
room("large giant scorpion")
for c in ("bles revolution", "l sc", "get sc", "dtch orc"):
    you(c)
    check(f"'{c}' doesn't arm it", not m.active)
st.manual_override = False
you("dtch sc")
check("switched off in settings: doesn't arm", not m.active)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
