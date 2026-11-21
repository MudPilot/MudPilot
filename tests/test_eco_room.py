"""0.8.53: Eco stops for the saracen leader → the whole room is fought (area spell); raiders swinging at you count."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 47
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, w = s.bot, s.world
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st.eco_travel = True; b.walking = True; b.loop = False
b.path = type("P", (), {"steps": [], "title": "Go to x"})()
b.eco_limits = lambda: (2350, 60)
lead = {"name": "saracen leader", "exp": 2000 * 2, "attack_data": {}}
rai = {"name": "saracen raider", "exp": 300, "attack_data": {}}
s.state.max_hp, s.state.hp = 684, 684
mobs = [("small saracen leader", lead)] + [(f"{a} saracen raider", rai) for a in ("large", "angry", "short", "fat")]
check("worth-it leader + raiders → all five fought", len(b._eco_filter(mobs)) == 5)
rest = mobs[1:]
check("raiders alone → walked past", b._eco_filter(rest) == [])
b._aggro = {"large saracen raider": time.time()}
check("…unless they're swinging at you", len(b._eco_filter(rest)) == 4)
# a pack: one locust nibbling is walked past; ten landing hits for 5%+ of max HP a round → wipe the room
b._aggro = {}
from mudpilot.gamestate import RoomView
s.state.view = RoomView("Blackwood Forest", {"N"}, [], [], [], time.time())
loc = {"name": "locust", "exp": 200, "attack_data": {}}
pack = [(f"locust", loc)] * 10
b.eco_note_hit("The locust bites you for 12 damage!")
check("one locust's bite (12 of 684) → walk on", b._eco_filter(pack[:1]) == [])
for _ in range(2):
    b.eco_note_hit("The locust bites you for 12 damage!")
check("three bites a round (36 ≥ 5% of 684) → clear the room", len(b._eco_filter(pack)) == 10)
b._eco_taken = [(t - 7, d) for t, d in b._eco_taken]
check("…and it's only the last round that counts", b._eco_filter(pack) == [])
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
