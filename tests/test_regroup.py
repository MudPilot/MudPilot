"""Party breaks while walking (room spell, warded arch, sinkhole): hold, find them, regroup — then carry on."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.megamud_files import Step, path_from_route
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
party = ["The following people are in your travel party:",
         "  Miserable Revolution          (Mage)       [M: 94%] [H:100%]  - Frontrank",
         "  Revolution Abil               (Druid)      [M:100%] [H:100%]  - Backrank", "[HP=684/MA=473]:"]

# --- dive sinkhole is magic: say it for the party first
feed(*party)
b.x._own_party = True
g.candidates = [(12, 1075)]
st.party_teleport_bring = True; st.party_say_cmds = []
sent.clear()
b._bring_party(Step("", 0, "dive sinkhole", [], (12, 1075), (12, 2224)), "dive sinkhole")
check("'dive sinkhole' (a teleport): '@party dive sinkhole' first", any(x.endswith("@party dive sinkhole") for x in sent))
b._bring = None

# --- a Go to; the party breaks on the way (no portal typed): hold and find him
target = (12, 2002)
mp = path_from_route(w, (12, 1811), w.route((12, 1811), target, level=47), name="Go to 12/2002 Great Pyramid")
g.candidates = [(12, 1811)]
b.start_path(mp, loop=False, checked=True)
b._goto_target = target
s.comeback._self_left = 0       # the '@party dive sinkhole' above was long ago (a party move expects a break for 20 s)
s.comeback.tick()                                   # remembers who's in the party
sent.clear()
feed("[HP=684/MA=443]:Revolution is no longer following you.", "Your party has been disbanded.",
     "Hidden Corridor, Carved Arch", "Obvious exits: northwest, southeast")
check("party broke: asks where he is", "/Revolution @where" in sent)
check(f"…and the Go to waits ({b.path and b.path.title} {s.comeback.fetch} {s.comeback.missing})", "comeback" in b.walk_holds())

# --- he joins again: no second invite
g.party = {"Miserable": {"hp": 100, "t": time.time()}}
feed("Revolution started to follow you.")
check("'started to follow you' puts him in the party straight away", "Revolution" in g.party)

# --- knocked flat: tell the party @held, and @ok once up
feed(*party)
st.report_conditions = True
sent.clear()
feed("You are knocked off your feet, and land with a heavy thump!", "You are flat on your back!")
check("knocked flat: '@held' for the party (once)", sent.count("@held") == 1)
sent.clear()
feed("You get back on your feet.")
check("…'@ok' when back up", "@ok" in sent)

# --- 'jump down' (12/2454) is a teleport too
g.candidates = [(12, 2454)]
sent.clear(); b._bring = None
b.x._own_party = True; g.party = {"Miserable": {"hp": 100, "t": time.time()}, "Revolution": {"hp": 100, "t": time.time()}}
b._bring_party(Step("", 0, "jump down", [], (12, 2454), (12, 1081)), "jump down")
check("'jump down' at 12/2454: '@party jump down' first", any(x.endswith("@party jump down") for x in sent))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
