"""PVE, 2026-10-29: 'recover corpse' put all its gear in the pack and nothing went back on — it fought unarmoured
and got poisoned through the headdress that negates it. What you had on goes back on."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g, b, r = s.state, s.bot, s.bot.redress
DRESSED = ("vortex staff (Weapon Hand), golden headdress (Head), shining metallic robes (Torso), silversilk gloves "
           "(Hands), silversilk trousers (Legs), simple sandals (Feet), platinum ring (Finger), lantern, 2 grey potion")
g.carrying, g.inv_seq = DRESSED, 1
r.login_checked = True
r.tick()
check(f"remembers what you wear ({st.last_worn})", "golden headdress" in st.last_worn and len(st.last_worn) == 7)
# died; recovered: all in the pack, nothing worn
g.carrying = ("vortex staff, golden headdress, shining metallic robes, silversilk gloves, silversilk trousers, "
              "simple sandals, platinum ring, lantern, 2 grey potion")
sent.clear()
b.note_line("You have recovered the corpse of Miserable.")
check(f"looks at the room first ({sent})", sent == [""])
# PvP (Dan, 2026-10-30): some of it lies outside the corpse — pick the floor up, all but copper / silver
from mudpilot.gamestate import RoomView
g.view = RoomView("Rotting Glade, Trail", {"N"}, [], [(1, "platinum mace"), (1, "silver ring"), (40, "copper farthings"),
                                                        (12, "silver nobles"), (200, "gold crowns")], [], time.time())
g.view_seq += 1
sent.clear(); r.tick()
check(f"picks up what fell out, not copper / silver coins ({sent})", "get platinum mace" in sent and
      "get silver ring" in sent and "get 200 gold crowns" in sent and not any("farthing" in c or "noble" in c for c in sent))
check(f"…then asks for the inventory ({sent})", sent[-1] == "i")
r.tick()
check("waits for it", not any(c.startswith("eq ") for c in sent))
g.inv_seq += 1
sent.clear(); r.tick()
eqs = [c for c in sent if c.startswith("eq ")]
check(f"puts it all back on ({eqs})", len(eqs) == 7 and "eq golden headdress" in eqs and "eq vortex staff" in eqs)
check("…remembered list isn't overwritten by the undressed inventory", len(st.last_worn) == 7)
# login: much less on than remembered → back on; a small difference (regen swap) → left alone
r2 = type(r)(b)
g.carrying = DRESSED.replace(" (Hands)", "").replace(" (Legs)", "").replace(" (Feet)", "")
g.inv_seq += 1
sent.clear(); r2.tick(); r2.tick()
check(f"logged in 3 pieces short: put back on ({sent})", sorted(c for c in sent if c.startswith("eq ")) ==
      ["eq silversilk gloves", "eq silversilk trousers", "eq simple sandals"])
r3 = type(r)(b)
g.carrying = DRESSED.replace(" (Hands)", "")
g.inv_seq += 1
sent.clear(); r3.tick(); r3.tick()
check(f"one piece off (a swap): left alone ({sent})", not any(c.startswith("eq ") for c in sent))
# Revolution, 2026-10-30: nothing remembered yet — wear the armour that came out of the corpse (not weapons)
st.last_worn = []
r4 = type(r)(b); r4.login_checked = True
g.view = RoomView("Rotting Glade, Trail", {"N"}, [], [], [], time.time())
for ln in ("You begin to pick through the corpse of Revolution...", "You took black star key.",
           "You took ogre-skin leggings.", "You took behemoth hide boots.", "You took vortex staff.",
           "You have recovered the corpse of Revolution."):
    r4.note_line(ln)
g.carrying = "41 gold crowns, ogre-skin leggings, behemoth hide boots, vortex staff, lantern"
g.view_seq += 1
r4.tick(); g.inv_seq += 1
sent.clear(); r4.tick()
eqs = [c for c in sent if c.startswith("eq ")]
check(f"nothing remembered: the corpse's armour goes on ({eqs})",
      "eq ogre-skin leggings" in eqs and "eq behemoth hide boots" in eqs and "eq vortex staff" not in eqs)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
