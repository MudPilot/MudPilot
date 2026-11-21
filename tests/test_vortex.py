"""A vortex breaks the party: the leader gets the follower through, and a following MudPilot goes after the leader."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
def mk(name):
    st = config.Settings(); st.save = lambda: None; st.my_name = name
    s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
    sent = []
    class Tel:
        connected = True
        events = __import__("queue").Queue()
        def send_line(self, x): sent.append(x)
        def close(self): self.connected = False
    s.telnet = Tel(); s._entered = True
    return s, st, sent
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

# --- leading: typed 'go vortex', the party broke, Revolution's still on the other side
s, st, sent = mk("Miserable")
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
feed("[HP=684/MA=473]:Negative Power Plane", "You notice whirling vortex here.", "Also here: Revolution.",
     "Obvious exits: northeast, northwest, southeast, southwest, up, down",
     "The following people are in your travel party:",
     "  Miserable Revolution          (Mage)       [M: 94%] [H:100%]  - Frontrank",
     "  Revolution Abil               (Druid)      [M:100%] [H:100%]  - Backrank", "[HP=684/MA=473]:")
s.bot.x._own_party = True
s.send("go vortex")
feed("You step into the swirling vortex, and find yourself... elsewhere.", "[HP=684/MA=473]:Revolution is no longer following you.",
     "Your party has been disbanded.", "Black Wasteland", "You notice whirling vortex here.", "Obvious exits: south, northeast")
b = s.bot._bring
check("the party breaking on 'go vortex' is noticed", b and b.get("broke") and b["cmd"] == "go vortex")
b["t"] -= 2
sent.clear(); s.bot.tick()
check("…Revolution is asked to come through", "/Revolution @do go vortex" in sent)
sent.clear(); s.bot.tick()
check("…once", "/Revolution @do go vortex" not in sent)
feed("[HP=684/MA=473]:Revolution steps out of the swirling vortex, looking somewhat disoriented.", "Black Wasteland",
     "You notice whirling vortex here.", "Also here: Revolution.", "Obvious exits: south, northeast")
sent.clear(); s.bot.tick()
check(f"…he's here: invited back, still waiting ({sent})", s.bot._bring is not None and "invite Revolution" in [x.lstrip('.') for x in sent])
feed("Revolution started to follow you.")
s.bot.tick()
check("…and the wait ends when he's joined", s.bot._bring is None)

# --- following: the leader went through and the party broke — go after them
s, st, sent = mk("Revolution")
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
feed("[HP=684/MA=473]:Negative Power Plane", "You notice whirling vortex here.", "Also here: Miserable.",
     "Obvious exits: northeast, northwest, southeast, southwest, up, down",
     "You are now following Miserable.",
     "The following people are in your travel party:",
     "  Miserable Revolution          (Mage)       [M: 94%] [H:100%]  - Frontrank",
     "  Revolution Abil               (Druid)      [M:100%] [H:100%]  - Backrank", "[HP=684/MA=473]:")
s.state.candidates = [(8, 958)]
feed("Miserable steps into the swirling vortex.", "Your party has been disbanded.")
s.bot.x._portal_watch["t"] -= 2
feed("[HP=684/MA=473]:Negative Power Plane", "You notice whirling vortex here.",
     "Obvious exits: northeast, northwest, southeast, southwest, up, down")
s.state.candidates = [(8, 958)]
sent.clear(); s.bot.x.portal_follow()
check("follower goes through the vortex after the leader", "go vortex" in sent)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
