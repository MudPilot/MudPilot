"""0.8.227.9 (Dan, 2026-11-27: "miserable pvp attacked captain, i'd like it to not attack npc's when you ask them
something that has no response.... it does this regularly"). 'ask cap list' → "old sea captain has nothing to tell
you!" read as the captain attacking ('you' + '!'): MudPilot cast magma blast, then swung at him, and his flintlock
killed Miserable. An NPC's no-answer isn't an attack."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g, w = s.bot, s.state, s.world
cap = w.monster_names["old sea captain"]
check(f"the captain isn't fought unprovoked (align {cap.get('align')})", not b.hostile(cap))
g.view = RoomView("Kingsport Harbor, Wharf", ["south"]); g.view.monsters = [("old sea captain", cap)]
g.party = {"Miserable": {}, "Revolution": {}}
for ln in ("old sea captain has nothing to tell you!", "The old sea captain has nothing to tell you!",
           "old sea captain doesn't know anything about that.", "The old sea captain ignores you.",
           "The old sea captain shakes his head at you!"):
    b._note_aggro(ln)
    g._unseen_monster(ln)
check(f"'has nothing to tell you!' and the like: not an attack ({getattr(b, '_aggro', {})})",
      not b._attacked_me("old sea captain"))
check(f"…nothing to attack ({[m for m, _ in b.attackable()]})", not b.attackable())
b._note_aggro("old sea captain levels his flintlock and fires at you for 406 damage!")
check("…but one that really shoots you is still fought back", b._attacked_me("old sea captain"))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
