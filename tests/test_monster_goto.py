"""Dan, 2026-10-30: 'I should be able to search for a monster… Sleazy shopkeeper is a shop about 8 rooms from where
we're at' — Goto (and @goto) find monsters by name and go where they stand / spawn / lair; and MME's shops and NPCs
are built into Goto's list (no Rooms.md needed)."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
w = s.world
sent, called = [], []
s.send = lambda c, from_bot=False: sent.append(c)
s.bot.goto = lambda k, ask=None, then=None: called.append(k) or True
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


sl = w.search_monsters("sleazy")
check(f"finds the sleazy shopkeeper ({[m['name'] for m in sl]})", sl and sl[0]["name"] == "sleazy shopkeeper")
check(f"…standing in the Musty Store 8/486 ({w.monster_rooms(sl[0]['num'])})",
      ((8, 486), "stands here") in w.monster_rooms(sl[0]["num"]))
bog = next(m for m in w.search_monsters("bog mummy"))
check("a lair monster lists its lair rooms", any(how == "lair" for _k, how in w.monster_rooms(bog["num"])))
pl = w.places()
check("MME shops are built in (Bank of Godfrey 1/297)", ("Shops", "Bank of Godfrey", (1, 297)) in pl)
s.state.candidates = [(8, 494)]
s.remote._channel = "telepath"
s.remote.c_goto("Dan", "sleazy shopkeeper")
check(f"@goto sleazy shopkeeper walks to 8/486 ({called}, {sent})", called == [(8, 486)])
s.remote.c_goto("Dan", "bank of godfrey")
check(f"…a room name still wins, nearest of two ({called})", called[-1] == (1, 297))
for a in ("17 1626", "17/1626", "17,1626", "map 17 room 1626"):
    called.clear(); s.remote.c_goto("Dan", a)
    check(f"@goto {a} → 17/1626 ({called})", called == [(17, 1626)])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
