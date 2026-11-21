"""A boss that can spawn in any of several lairs — the crimson mist, any of 16 round the Ancient Ruin — gets a sweep:
the lairs nearest-next from where it was last killed, a quick look in each, fight it wherever it shows, give up only
after the whole round (Dan, 2026-11-02)."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config, bosses
from mudpilot.session import Session
from mudpilot import bosshunt as BH
bosses.BOSS_FILE_OVERRIDE = os.path.join(config.DATA_DIR, "test-bosshunt-sweep.json")
try: os.remove(bosses.BOSS_FILE_OVERRIDE)
except OSError: pass
st = config.Settings(); st.save = lambda: None; st.boss_farm_on = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.bosses.load()
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): pass
s.telnet = Tel(); s._entered = True
b, w, g = s.bot, s.world, s.state
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
mon = w.monster_names["crimson mist"]
lairs = s.bosshunt.lairs(mon)
check(f"the mist's lairs found ({len(lairs)})", len(lairs) >= 10 and all(k[0] == 3 for k in lairs))
calls = []
b.plan_route = lambda a, c, ask=None: [1] * 10
b.goto = lambda room, then=None, ask=None: calls.append(room) or True
plaza = (3, 560)
start = w.by_name["ancient ruin, inside arch"][0] if w.by_name.get("ancient ruin, inside arch") else lairs[0]
g.candidates = [start]; g.max_hp = g.hp = 800
b.walking, b.loop, b.path = False, False, None; b.status = "Arrived"
rec = s.bosses.rec(mon)
rec["hunt"] = True
rec["dead_since"] = time.time() - mon["regen_h"] * 3600 - 60
last = lairs[5]
rec["kills"] = [{"t": rec["dead_since"], "by": "you", "room": list(last)}]
s.bosses.save()
s.bosshunt.tick()
a = s.bosshunt.active
check(f"due: off to where it was last killed first ({calls})", calls == [last] and a and a["lairs"] == len(lairs))
# not there: on to the next lair after a quick look
g.candidates = [last]
a["arrived"] = time.time() - BH.SWEEP_LOOK - 1
s.bosshunt.tick()
check(f"not in that lair: next one ({calls[-1]}, {len(a['sweep'])} left)", len(calls) == 2 and calls[1] != last
      and len(a["sweep"]) == len(lairs) - 2)
seen = set(calls)
# walk the rest without it showing up
for _ in range(len(lairs)):
    if not s.bosshunt.active:
        break
    g.candidates = [s.bosshunt.active["room"]]
    s.bosshunt.active["arrived"] = time.time() - BH.SWEEP_LOOK - 1
    s.bosshunt.tick()
    seen |= set(calls)
check(f"every lair checked once ({len(seen)} of {len(lairs)})", seen >= set(lairs))
check("…then it gives up for this spawn", s.bosshunt.active is None)
# found in the middle of a sweep: killed → done, no more lairs
rec["hunt_tried"] = None; calls.clear()
rec["dead_since"] = time.time() - mon["regen_h"] * 3600 - 60
g.candidates = [start]
s.bosshunt.tick()
s.bosses.record_kill(mon)
s.bosshunt.tick(); s.bosshunt.active["killed"] -= 10; n = len(calls)
s.bosshunt.tick()
check("killed mid-sweep: stops sweeping", s.bosshunt.active is None and not any(c in lairs for c in calls[n:]))
os.remove(bosses.BOSS_FILE_OVERRIDE)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
