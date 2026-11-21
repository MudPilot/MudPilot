"""Dan, 2026-11-04: '@hunt crimson mist' starts a hunt; a bare '@hunt' should show the bosses he's hunting; '@hunt off'
when you take over leading the party stops him hunting entirely."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.bosses.save = lambda: None
r, bh, b = s.remote, s.bosshunt, s.bot
check(f"nothing ticked: says so ({r.c_hunt('Dan', '')})", "not hunting" in str(r.c_hunt("Dan", "")))
now = time.time()
s.bosses.data = {"309": {"name": "crimson mist", "kills": [], "manual": True, "hunt": True, "check_at": now + 3600},
                 "1093": {"name": "x", "kills": [], "hunt": True, "dead_since": now - 3600},
                 "500": {"name": "y", "kills": [], "dead_since": now - 60}}                  # not ticked for hunting
out = r.c_hunt("Dan", "")
check(f"bare @hunt lists the hunted ones ({out})", isinstance(out, list) and len(out) == 2
      and any(x.startswith("crimson mist:") and "looking again in" in x for x in out))
bh.active = {"num": 309, "name": "crimson mist", "lairs": 16, "sweep": [1] * 10}
out = r.c_hunt("Dan", "")
check(f"the one under way first ({out})", out[0] == "hunting crimson mist now - 6 of 16 lairs checked"
      and not any(x.startswith("crimson mist:") for x in out))
# @hunt off: ends the hunt where it is, no walk back, nothing due starts
stopped = []
b.walking = True
b.stop = lambda why="", **k: stopped.append(why)
gone = []
b.goto = lambda *a, **k: gone.append(a) or True
msg = r.c_hunt("Dan", "off")
check(f"@hunt off ({msg})", "off" in msg and bh.active is None and stopped and not gone
      and not st.boss_hunt_on and not st.boss_farm_on)
check("…and nothing starts on the next tick", not (st.boss_hunt_on or st.boss_farm_on))
check(f"@hunt on ({r.c_hunt('Dan', 'on')})", st.boss_hunt_on and st.boss_farm_on)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
