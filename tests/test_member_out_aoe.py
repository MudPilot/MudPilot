"""Dan, 2026-11-18: Miserable hung up, logged back in 8 minutes later where he'd left — straight into Revolution's
repeating tempest. Someone outside the party walking in (PvP realm): single-target at once, and a repeating area spell
breaks off."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"; st.pvp_realm = True
s = Session(st); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
b, x, gs = s.bot, s.bot.x, s.state
b.send = lambda c, *a, **k: sent.append(c)
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
gs.party = {"Miserable": {}, "Revolution": {}}
x._following = "Miserable"
gs.view = RoomView("Bristlewood Grove", {"N"}, [], [], [], time.time() - 5)
check("all here → area spells fine", b.aoe_blocked() is None)
x.note_line("Miserable just hung up!")
check("a member hanging up doesn't hold area spells (Dan: rooms spawn big)", b.aoe_blocked() is None)
gs.party = {"Revolution": {}}                 # the party broke when he dropped
x.note_line("Miserable walks into the room from nowhere.")
check(f"logs back in here → single-target at once ({b.aoe_blocked()})",
      b.aoe_blocked() and "Miserable" in b.aoe_blocked())
gs.view = RoomView("Bristlewood Grove", {"N"}, [], [], [], time.time() + 1)
check("fresh room list after: it decides (he's in the party again / not listed)", b.aoe_blocked() is None)
x._walked_in = None
st.pvp_realm = False
x.note_line("Bob walks into the room from the north.")
check("PVE realm: nothing held", b.aoe_blocked() is None)
st.pvp_realm = True
# walks in during the repeating area spell → break
gs.party = {"Revolution": {}}
gs.in_combat = True
b._area_cast_t = time.time()
sent.clear()
x.note_line("Miserable walks into the room from nowhere.")
check(f"walked in mid area spell → break ({sent})", st.break_cmd in sent)
sent.clear()
x.note_line("Bob walks into the room from the north.")
check("no area spell going any more → nothing sent", not sent)
b._area_cast_t = time.time()
gs.party = {"Revolution": {}, "Bob": {}}
x.note_line("Bob walks into the room from the north.")
check("a party member walking in → no break", not sent)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
