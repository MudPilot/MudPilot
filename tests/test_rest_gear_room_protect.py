"""0.8.227.8 (Dan: "Mudpilot fightin me bout died... It should know it needs a phoenix feather in this area and not eq
the sparkling pendant during rest"). Miserable PVE rested in the Volcanic Chamber; the regen set swapped the phoenix
feather off for the sparkling pendant and the room seared him for 40-60 a tick down to 27 HP. Whatever stops the
room's spell stays on now, and a room that hurts mid-rest gets the fighting set straight back and no swap again."""
import os, sys, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_rest_gear_room"))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

st = config.Settings(); st.save = lambda: None; st.save_quietly = lambda *a, **k: None; st.auto_regen_gear = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent, logs = [], []
s.send = lambda c, from_bot=False: sent.append(c)
s.log = lambda m, *a, **k: logs.append(m)
w, b, g = s.world, s.bot, s.state
CARRY = ("1 runic coin, 520 gold crowns, golden headdress (Head), crimson earrings (Ears), mask of the farseer (Face), "
         "phoenix feather (Neck), faded shawl (Back), shining metallic robes (Torso), silver-threaded armwraps (Arms), "
         "sunstone wristband (Wrist), ivory bracelet (Wrist), silversilk gloves (Hands), platinum ring (Finger), "
         "tarnished band (Finger), sash of the arch wizard (Waist), spider silk trousers (Legs), simple sandals (Feet), "
         "severed head of Goru-Nezar (Worn), rift staff (Weapon Hand), magical quartz rod, white gold ring, runed cape, "
         "sparkling pendant, golden vial, swamp boots")
g.carrying = CARRY; g.level = 62
chambers = [k for k, r in w.rooms.items() if r.name == "Volcanic Chamber" and (w.room_spells or {}).get(k)]
check(f"the Volcanic Chamber has a room spell ({chambers[:3]})", bool(chambers))
room = chambers[0]
sp = w.room_spells[room]
check(f"…the phoenix feather stops it", "phoenix feather" in {w.item_name(i).lower() for i in w._spell_rel(int(sp))})
# away from the heat the pendant goes on as before
g.candidates = [(1, 1)]
on, back = b._regen_gear("rest")
check(f"control, a safe room: the pendant goes on ({on})", any("sparkling pendant" in c for c in on))
g.candidates = [room]
on, back = b._regen_gear("rest")
check(f"in the Volcanic Chamber: the feather stays on ({on})", not any("sparkling pendant" in c for c in on)
      and not any("phoenix" in c for c in on + back if c.startswith("remove")))
check(f"…other slots still swap ({on})", any(c.startswith("eq ") for c in on))
# a room MME doesn't know hurts: the first 'seared' line puts the fighting set back and no swap again here
g.candidates = [(1, 1)]
b._swap = None
b._begin_swap("rest")
check(f"swapped into the regen set ({sent})", b._swap == "rest" and any("sparkling pendant" in c for c in sent))
sent.clear()
g.in_combat = False
b.note_line("You are seared by the flames for 49 damage!")
check(f"'seared' mid-rest: the feather goes straight back on ({sent})", b._swap is None
      and any(c == "eq phoenix feather" or c.startswith("eq phoenix") for c in sent))
sent.clear()
b._begin_swap("rest")
check(f"…and no swap again in that room ({sent})", not any("sparkling pendant" in c for c in sent))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
