"""Gear modes: meditate gear goes on when you sit down to meditate, Base gear when you get up."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None
s = Session(st); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
g = s.gearmodes
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
s.state.carrying = "silver ring (Finger), padded robe (Torso), quarterstaff (Weapon Hand), mana ring, silk robe"
g.capture("base")
s.state.carrying = "mana ring (Finger), silk robe (Torso), quarterstaff (Weapon Hand), silver ring, padded robe"
g.capture("meditate")
check("meditate set differs from base in two slots", g.wanted("meditate") == {"Finger": "mana ring", "Torso": "silk robe", "Weapon Hand": "quarterstaff"})
s.state.carrying = "silver ring (Finger), padded robe (Torso), quarterstaff (Weapon Hand), mana ring, silk robe"
st.gear_modes_on = True
s.state.resting, s.state.meditating = True, True
g.tick(); g._since -= 5; g.tick()
check(f"sat down to meditate → swaps in the meditate gear ({sent})",
      sent[:4] == ["remove silver ring", "wear mana ring", "remove padded robe", "wear silk robe"] and sent[-1] == "i")
sent.clear()
s.state.carrying = "mana ring (Finger), silk robe (Torso), quarterstaff (Weapon Hand), silver ring, padded robe"
s.state.resting = s.state.meditating = False
g._sent_at = 0
g.tick(); g._since -= 5; g.tick()
check(f"stood up → Base gear back ({sent})", "wear silver ring" in sent and "wear padded robe" in sent)
sent.clear()
st.gear_modes = {"base": {"Finger": "gold ring"}}
g._applied = None; g._sent_at = 0
s.state.carrying = "silver ring (Finger)"
g.tick(); g._since -= 5; g.tick()
check("item not carried → skipped, nothing sent", not sent)
# Revolution, 2026-11-06: Base was captured as one item a slot; wearing the sunstone wristband and the sash of the
# arch-mage as the second Wrist / Worn item, they came off and 'wear diamond emblem' went to an emblem already on
sent.clear()
st.gear_modes = {"base": {"Wrist": "emerald-studded bracelet", "Worn": "diamond emblem", "Finger": "platinum ring"}}
g._applied = None; g._sent_at = 0
s.state.carrying = ("emerald-studded bracelet (Wrist), sunstone wristband (Wrist), platinum ring (Finger), "
                    "diamond emblem (Worn), sash of the arch-mage (Worn), pearl ring")
g.tick(); g._since -= 5; g.tick()
check(f"second wrist / Worn items stay on ({sent})", not sent)
# a slot with room: Base's emblem goes on beside the sash — nothing comes off
sent.clear(); g._applied = None; g._sent_at = 0
s.state.carrying = "sash of the arch-mage (Worn), diamond emblem"
g.tick(); g._since -= 5; g.tick()
check(f"emblem goes on beside the sash ({sent})", sent[:1] == ["wear diamond emblem"] and not any(c.startswith("remove") for c in sent))
# captured with two on: both stored, both wanted
s.state.carrying = "emerald-studded bracelet (Wrist), sunstone wristband (Wrist), diamond emblem (Worn)"
g.capture("pvp")
check(f"capture keeps both wrists ({st.gear_modes['pvp']})",
      st.gear_modes["pvp"]["Wrist"] == ["emerald-studded bracelet", "sunstone wristband"])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
