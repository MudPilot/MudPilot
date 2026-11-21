"""Real Paradigm lines from pMUD's incident logs that MudPilot used to get wrong."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.worlddb import DIR_WORDS
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st); s._no_log_file = True
sent, closed = [], []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): closed.append(1); self.connected = False
s.telnet = Tel(); s._entered = True
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
g, w = s.state, s.world
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)

feed("The following people are in your travel party:",
     "  Phrixas                       (Mystic)     [H:100%]  - Frontrank",
     "  Miserable Par                 (Mage)       [M: 69%] [H: 96%]M - Frontrank",
     "  Deacon                        (Priest)     [M: 50%] [H: -5%]  - Backrank",
     "  Setra                         (Bard)       [Invited]")
check(f"party rows without a mana bar, negative HP, invited ({sorted(g.party)})",
      set(g.party) == {"Phrixas", "Miserable", "Deacon"} and g.party["Deacon"]["hp"] == -5)
feed("Deacon is no longer following you.")
check("'X is no longer following you' drops them from the party", "Deacon" not in g.party)
feed("Your party has been disbanded.")
check("'Your party has been disbanded.' clears the party", not g.party)

# "Deacon*" in Also here
k = next(k for k, r in w.rooms.items() if w.is_room_name(r.name) and len(w.by_name.get(r.name.lower(), [])) == 1
         and any(e.kind == "normal" for e in r.exits.values()))
r = w.room(k)
ex_line = "Obvious exits: " + ", ".join(DIR_WORDS[d] for d, e in r.exits.items() if e.kind == "normal")
g.candidates = [k]
feed(r.name, "Also here: Deacon*, dark wyrm.", ex_line)
check(f"'Deacon*' is the player Deacon ({g.view.players})", "Deacon" in g.view.players)

# failed look doesn't eat the next move
g.candidates = [k]
d, e = next((d, e) for d, e in r.exits.items() if e.kind == "normal")
g.note_command("l sw" if "SW" not in r.exits else "l nw")
feed("There is no exit in that direction!")
check("failed 'look <dir>' is dropped from the queue", not g.pending)

# wrapped exits
dest = w.room(e.to)
parts = [DIR_WORDS[x] for x, ee in dest.exits.items() if ee.kind == "normal"]
g.candidates = [k]
g.note_command(d.lower())
if len(parts) >= 2:
    feed(dest.name, "Obvious exits: " + ", ".join(parts[:-1]) + ",", parts[-1])
else:
    feed(dest.name, "Obvious exits: " + parts[0])
check(f"exits list wrapped onto a second line still places the room ({g.room} vs {e.to})", g.room == e.to)

# confusion
g.candidates = [k]
g.note_command(d.lower())
feed("You fumble in confusion!")
check("'You fumble in confusion!' = the move didn't happen", not g.pending and g.room == k)

# negative HP prompt
g._check_prompt("[HP=-3/MA=52]:")
check(f"negative HP read ({g.hp})", g.hp == -3)

# chat isn't the game
g.dead = False; g.candidates = [k]
feed("Bob gossips: lol you have been killed")
check("a gossip saying 'you have been killed' isn't your death", not g.dead and g.candidates == [k])
k0 = g.kills
feed("You gain 0 experience.")
check("0 experience isn't a kill", g.kills == k0)
feed("You gain 13000 experience.", "You gain 13000 experience.")
check("two exp lines = two kills", g.kills == k0 + 2)

# arrivals
for line in ("A large dark treant thunders in from the east!", "A big dustdevil suddenly forms beside you!",
             "The kobold runs out of the room to the west!", "Deacon just left to the north."):
    g.need_refresh = False
    feed(line)
    check(f"arrival/departure noticed: {line}", g.need_refresh)

# invites
feed("Phrixas has invited you to follow him.")
from mudpilot.players import INVITE_RE
check("'has invited you to follow him' is an invite", INVITE_RE.match("Phrixas has invited you to follow him."))
# dark room with no title keeps the place the move led to
g.candidates = [k]; g.note_command(d.lower())
feed("The room is very dark - you can't see anything", "Obvious exits: north")
check(f"dark room with no title: placed by the move ({g.candidates})", g.candidates and g.candidates[0] == e.to)

# benign cast isn't PvP
st.hangup_on_pvp = True
feed("Bob casts merciful grace upon you!")
check("'Bob casts merciful grace upon you!' isn't PvP", not closed)

# jail
g.candidates = [k]; g.pending.append(("move", "N", [k]))
feed("Battered and beaten, you are knocked unconscious and dragged off to jail!")
check("jail: the planned move is forgotten", not g.pending and not g.candidates)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
