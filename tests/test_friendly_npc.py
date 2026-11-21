"""Dan, 2026-11-05: turning in the chalice, "mudpilot tried to smash" the bishop. 'The bishop smiles at you
hopefully' read as the bishop going for Buddy — and a lawful-good NPC that attacks you gets fought back. Talking
and smiling at you isn't attacking."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g, w = s.bot, s.state, s.world
bishop = w.monster_names["bishop"]
v = RoomView("Temple Chapel", ["east"]); v.monsters = [("bishop", bishop)]
g.view = v
for ln in ('The bishop says, "Yes, the chalice of Amilan, our most precious holy artifact, has been stolen!',
           'The bishop smiles at you hopefully, and says, "Have you found the chalice?"',
           'The bishop exclaims, "Wonderful, adventurer! And here is your reward!"',
           "The bishop gives you a jade amulet.", "The bishop gives you some white satin gloves."):
    b._note_aggro(ln)
check(f"the chalice turn-in: the bishop's not after you ({getattr(b, '_aggro', {})})", not b._attacked_me("bishop"))
check("…and lawful good stays off the list", not b.hostile(bishop))
b._note_aggro("The bishop lunges at you!")
check("one that does go for you is still fought back", b._attacked_me("bishop"))
# Miserable PVE, 2026-11-06: "The ghost gives you a stern look, \"Be wary…" put an (evil) 'ghost' on the room's
# list beside the Ghost of Justice Darkbane, and he cast magic missile at the ghost
jd = w.monster_names["ghost of justice darkbane"]
g.view = RoomView("Pristine Shrine", ["east"]); g.view.monsters = [("Ghost of Justice Darkbane", jd)]
g.party = {"Buddy": {}, "Revolution": {}}
for ln in ("Justice Darkbane arches a ghostly eyebrow at you...",
           'The ghost gives you a stern look, "Be wary of these monsters for they are very powerful, and Ozrinom is',
           'not possible to reach by mortal means." With that he bows to you, "Best of luck, for you will need all"'):
    g._unseen_monster(ln)
    b._note_aggro(ln)
check(f"Justice Darkbane's warning: no 'ghost' added ({[m for m, _ in g.view.monsters]})",
      [m for m, _ in g.view.monsters] == ["Ghost of Justice Darkbane"])
check(f"…and nothing to attack ({[m for m, _ in b.attackable()]})", not b.attackable())
# a real one in the dark still goes on the list
g.view = RoomView("(dark)", None); g.view.monsters = []
g._unseen_monster("The tall dark-elf sentry swings at you with a scimitar!")
check(f"the dark room's sentry still counted ({[m for m, _ in g.view.monsters]})",
      [m for m, _ in g.view.monsters] == ["tall dark-elf sentry"])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
