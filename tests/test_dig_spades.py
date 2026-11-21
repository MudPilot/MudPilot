"""Dan, 2026-10-28: a dig loop ('dig treasure' in one room, over and over) — "Nothing happens." means you're out of
spades (MME: dig treasure checks item 3404, spade). Read the inventory; none left → stop, and say so."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import Step
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent, alerts = [], []
s.send = lambda c, from_bot=False: sent.append(c)
s.on_alert = lambda m: alerts.append(m)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
b, g = s.bot, s.state
step = Step("", 0, "", ["dig treasure"], (13, 211), (13, 211))
b.walking = True
now = time.time()
b._stay_step(step, now)
check(f"digs ({sent})", sent == ["dig treasure"])
sent.clear()
b.note_line("Nothing happens.")
check(f"'Nothing happens.' → reads the inventory ({sent})", sent == ["i"])
g.carrying = "917 silver nobles, bone club, vortex staff (Weapon Hand), 2 rations"
g.inv_seq += 1
b._stay_sent = None
b._stay_step(step, time.time())
check(f"no spade left → stops ({b.walking}, {alerts})", not b.walking and any("spade" in a for a in alerts))
# still has spades: carries on
b.walking, alerts[:] = True, []
b._dig_nothing = 0
b._stay_sent = None
sent.clear()
b._stay_step(step, time.time())
b.note_line("Nothing happens.")
g.carrying = "3 spade, vortex staff (Weapon Hand)"
g.inv_seq += 1
b._stay_sent = None
sent.clear()
b._stay_step(step, time.time())
check(f"spades left → keeps digging ({sent}, walking={b.walking})", b.walking and sent == ["dig treasure"])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
