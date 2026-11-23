"""HUNT_1123 #19: an errand's item-source search honours the door you said "try anyway" to (and the start-room HP pass).
An L8 (0 picklocks, 20 strength, 60 HP) at 8/838 Hilltop Fortress → 1/1327: the Go to tries the 41-picklock down door
(you said yes), then needs a crowbar — 8 shops sell one, but dist_map counted that door as a wall and the reason came out
"the crowbar drops off the Giovanni, too strong for you"."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 8
st.char_class = "Warrior"; st.char_race = "Human"; st.char_alignment = "Good"
st.hangup_low_hp = True; st.hangup_hp_pct = 25
s = Session(st, world_path=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.state.inv_at = float("inf")
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T(); s._entered = True
logs = []
s.log = lambda m, *a, **k: logs.append(str(m))
s.on_no_route = lambda m: None
s.on_alert = lambda m: None
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
w, b, g = s.world, s.bot, s.state
b._ask_gate_abilities = lambda *a, **k: False
b._reread_flags = lambda *a, **k: False
if (8, 838) not in w.rooms or (1, 1327) not in w.rooms:
    print("SKIP (no Paradigm map)"); sys.exit(0)

def at(room, ask):
    b.stop("t"); b.errands.cancel(); s.trips.reset("test")
    b._pending_abil = None; b._pending_goto = None; b._door_yes = {}; w.door_yes = {}
    g.candidates = [room]; g.level = 8
    g.carrying = "You are carrying nothing"; g.keys = ""; g.inv_seq += 1
    g.picklocks, g.strength = 0, 20
    g.max_hp = g.hp = 60; g.max_hp_read = True; g.wealth = 200
    w.forget_routes(); w.refused_doors = {}
    b._cool.pop("goto_st", None)
    logs.clear(); b.no_route_msg = ""
    asks = []
    b.goto((1, 1327), ask=lambda *a, **k: (asks.append(a), ask)[1])
    return asks

asks = at((8, 838), True)
text = " | ".join(logs)
check(f"asked about the door ({len(asks)})", any("door" in str(a) for a in asks))
check("no 'too strong' Giovanni refusal", "Giovanni" not in (b.no_route_msg or "") and "Giovanni" not in text)
check(f"fetches a crowbar from a shop ({(b.no_route_msg or text)[-160:]!r})",
      "crowbar (sold:" in text and "Detouring to" in text)

asks = at((8, 838), False)
check(f"said no: the door is named, not Giovanni ({(b.no_route_msg or '')[:90]!r})",
      "Giovanni" not in (b.no_route_msg or "") and "nobody in the party can open it" in (b.no_route_msg or ""))

# dist_map: a hopeless door counts only once you said yes to it
ex = w.rooms[(8, 838)].exits["D"]; w.refused_doors = {}
w.door_yes = {}
check("door_refused without a yes", w.door_refused(ex, set()))
w.door_yes = {id(ex): time.time()}
check("door_refused after a yes: no", not w.door_refused(ex, set()))
w.door_yes = {id(ex): time.time() - 4 * 3600}
check("…a yes 4 hours old: refused again", w.door_refused(ex, set()))
w.door_yes = {}
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
