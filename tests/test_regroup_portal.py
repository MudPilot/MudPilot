"""0.8.52: the party broke going through a portal and Revolution came through right behind: invite him back and
don't walk on until he's joined."""
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
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
feed("[HP=684/MA=403]:Negative Power Plane", "You notice nightblack portal here.", "Also here: Revolution, big ju-ju zombie.",
     "Obvious exits: northeast, northwest, southeast, southwest, up, down",
     "The following people are in your travel party:",
     "  Miserable Revolution          (Mage)       [M: 94%] [H:100%]  - Frontrank",
     "  Revolution Abil               (Druid)      [M:100%] [H:100%]  - Backrank", "[HP=684/MA=403]:")
s.bot.x._own_party = True
s.send("go portal")
feed("You step into the dark portal, and a wrenching sensation envelops you!",
     "[HP=684/MA=403]:Revolution is no longer following you.", "[HP=684/MA=403]:Your party has been disbanded.",
     "Limestone Caverns", "You notice nightblack portal here.", "Obvious exits: east")
b = s.bot._bring
check("the break is noticed", b and b.get("broke"))
sent.clear()
feed("[HP=684/MA=403]:Revolution appears in a flash of light!")
check(f"he appears: look straight away ({sent})", "" in sent)
feed("[HP=684/MA=403]:", "Limestone Caverns", "You notice nightblack portal here.", "Also here: Revolution.",
     "Obvious exits: east")
sent.clear()
held = s.bot._waiting_for_party_through(time.time())
check(f"he's here but not in the party: invited, and the walk waits ({sent})", held and "invite Revolution" in [x.lstrip('.') for x in sent])
b["t"] -= 60
check("…still waiting a minute later (no giving up while he's standing here)", s.bot._waiting_for_party_through(time.time()))
feed("Revolution started to follow you.")
check("he joins: carry on", not s.bot._waiting_for_party_through(time.time()) and s.bot._bring is None)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
