"""Dan, 2026-11-01: "No walkable route — blocked by the west exit of Temple Foyer (1/2316): (Alignment: Saint to
Seedy)". Buddy is Good. MudPilot had never learned its own alignment (it skipped your own line in 'who'), so every
alignment gate looked shut. It reads it off 'who' now, and checks 'who' itself when a gate's in the way."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


w = s.world
gate = w.room((1, 2316)).exits["W"]
check(f"the Temple Foyer gate ({gate.etype})", "Saint to Seedy" in gate.etype)
s.route_char()
check("alignment unknown: the gate's shut", not w.gate_ok(gate))
for ln in ("         Current Adventurers", "         ===================", "",
           "    Good Buddy Revolution        -  Squire",
           "         Revolution Medi         -  Acolyte",
           "   Seedy Zimmer                  -  Thief"):
    s.players.feed_line(ln)
s.players.feed_line("[HP=303/MA=98]:")
s.players._who_finish()
check(f"own line in 'who' read ({s.state.alignment})", s.state.alignment == "Good")
check("…and the gate's open for a Good character", w.gate_ok(gate))
# kept on your own record: a restart (alignment forgotten in the state) still knows it (Miserable PVE, 2026-11-06)
check(f"…saved on your own player record ({s.players.data.get('buddy', {}).get('alignment')})",
      s.players.data.get("buddy", {}).get("alignment") == "Good")
s.state.alignment = ""
s.route_char()
check("…so after a restart the gate's open before any 'who'", w.gate_ok(gate))
s.state.alignment = ""
s.players.data.pop("buddy", None)
for ln in ("         Current Adventurers", "         Buddy Revolution        -  Squire"):
    s.players.feed_line(ln)
s.players._who_finish()
check(f"blank in 'who' is Neutral ({s.state.alignment})", s.state.alignment == "Neutral")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
