"""0.8.208 (Dan, 2026-11-19): Evolution walked the Vine Bridge's spell trap east of 16/1206 ('(Spell Trap: 851)') without
disarming it and was dropped into the mists. Spell traps are 'restricted' for the router; the walk disarms them too."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import Step
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"; st.disarm_traps = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
b, w = s.bot, s.world
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
ex = w.rooms[(16, 1206)].exits["E"]
check(f"the bridge exit is a spell trap ({ex.kind}: {ex.etype})", "spell trap" in ex.etype.lower())
stp = Step("", 0, "E", [], (16, 1206), (16, 1207))
check(f"walking east off 16/1206: disarm first ({sent})", b._disarm_gate(stp, (16, 1206)) and
      any(x.startswith("disarm trap e") for x in sent))
b._disarm_line("You successfully disarmed the trap to the east!")
check("…disarmed: walk on", not b._disarm_gate(stp, (16, 1206)))
plain = Step("", 0, "W", [], (16, 1206), (16, 1205))
b._disarm = None; sent.clear()
check("an ordinary exit: no disarm", not b._disarm_gate(plain, (16, 1206)) and not sent)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
