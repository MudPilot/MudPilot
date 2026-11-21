"""0.8.52: a path step '@party go vortex' sends 'go vortex' itself too; learned exits never store @ commands."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.worlddb import clean_move
from mudpilot.session import Session
from mudpilot.megamud_files import Step, MPath

ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)

check("'@party go vortex' → 'go vortex'", clean_move("@party go vortex") == "go vortex")
check("'.@party dive sinkhole' → 'dive sinkhole'", clean_move(".@party dive sinkhole") == "dive sinkhole")
check("'@where' isn't a move", clean_move("@where") == "")
check("'go path' stays", clean_move("go path") == "go path")

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
w = s.world
src = next(k for k, r in w.rooms.items() if len(r.exits) >= 1)
dst = next(k for k in w.rooms if k != src and k[0] == src[0])
check("learning '@party go vortex' stores 'go vortex'", w.add_learned(src, "@party go vortex", dst)
      and any(e.accepts("go vortex") for e in w.rooms[src].exits.values() if e.to == dst))
check("learning '@where' stores nothing", not w.add_learned(src, "@where", dst))

sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
b, g = s.bot, s.state
from mudpilot.ansi import Style
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
st.party_teleport_bring = True; st.auto_spells = st.auto_bless = st.auto_rest = st.auto_heal = False
feed("The following people are in your travel party:",
     "  Miserable Revolution          (Mage)       [M: 94%] [H:100%]  - Frontrank",
     "  Revolution Abil               (Druid)      [M:100%] [H:100%]  - Backrank", "[HP=684/MA=473]:")
b.x._own_party = True
r = w.rooms[(3, 731)]
mp = MPath("Go to 8/958", "", "", "", steps=[Step("", 0, "@party go vortex", [], (3, 731), (8, 958))],
           resolved=True, resolve_note="built from MME")
feed("[HP=684/MA=473]:" + r.name, "Also here: Revolution.", "Obvious exits: " + ", ".join(
     {"N": "north", "S": "south", "E": "east", "W": "west", "NE": "northeast", "NW": "northwest", "SE": "southeast",
      "SW": "southwest", "U": "up", "D": "down"}.get(d, d) for d in r.exits if len(d) <= 2) or "none")
g.candidates = [(3, 731)]
b.start_path(mp, loop=False, checked=True)
sent.clear()
for _ in range(6):
    b.tick()
    if "go vortex" in [x.lstrip(".") for x in sent]:
        break
plain = [x.lstrip(".") for x in sent]
check(f"step '@party go vortex': the party is told AND Miserable goes ({sent})",
      "@party go vortex" in plain and "go vortex" in plain and plain.index("@party go vortex") < plain.index("go vortex"))

# --- you move by hand mid-walk: it stops until Rego
b._bring = None
g.candidates = [(3, 731)]
b.start_path(mp, loop=False, checked=True)
s.send("n")
check(f"typed 'n' while walking: stopped ({b.status})", not b.walking and "Rego" in b.status)
check("…and Rego has something to carry on with", b.resume is not None)
# a comeback fetch was going to carry on to the Go to afterwards: moving by hand cancels that too
s.comeback.fetch = {"name": "Revolution", "phase": "going", "room": (3, 731), "back": ("goto", (8, 958)), "t": time.time()}
s.send("s")
check("moving by hand: the fetch won't drag you back onto the trip", s.comeback.fetch["back"] is None)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
