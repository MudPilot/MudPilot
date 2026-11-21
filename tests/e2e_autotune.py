"""Auto-tune on the practice server: each trial waits for the loop's first room, tops up to full,
times whole laps, and the best setting is kept."""
import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
from mudpilot.megamud_files import path_from_route
PORT = 2419
world = WorldDB(config.WORLD_DB)
sim = simserver.Sim(world, seed=5, mob_rate=0.3)
def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r, w: simserver.handle(sim, r, w), "127.0.0.1", PORT)
        async with srv:
            await srv.serve_forever()
    asyncio.run(go())
threading.Thread(target=run_server, daemon=True).start()
time.sleep(0.5)
st = config.Settings(); st.save = lambda: None
st.host, st.port, st.username = "127.0.0.1", PORT, "Tester"
st.auto_reconnect = False; st.auto_combat = True; st.auto_rest = True; st.min_mobs, st.max_mobs = 1, 3
st.attack_good = st.attack_neutral = True; st.stop_before_boss = False
st.rest_below_hp, st.rest_until_hp = 60, 90
s = Session(st); s.password = "x"; s._no_log_file = True
import tempfile
_tmp = tempfile.mkdtemp(); config.board_dir = lambda bd: os.path.join(_tmp, bd)
s.connect()
def run(secs, until=None):
    end = time.time() + secs
    while time.time() < end:
        s.poll()
        if until and until():
            return True
        time.sleep(0.03)
    return False
run(4, lambda: s.state.room is not None and s._entered)
here = s.state.room
loop = path_from_route(world, (1, 1), world.route((1, 1), (1, 16)) + world.route((1, 16), (1, 1)), name="tune loop")
s.bot.goto((1, 1), then=loop)
run(60, lambda: s.bot.walking and s.bot.path is loop and s.bot.idx > 2)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st.tune_mins = 0.15
msg = s.autotune.start(0.15, 1)
print("  ", msg)
check("waits for the start of the loop first", s.autotune.phase == "to_start")
phases = set()
starts = []
orig = s.autotune.lap_end
def spy():
    starts.append(s.state.room)
    orig()
s.autotune.lap_end = spy
done = run(500, lambda: (phases.add(s.autotune.phase) or not s.autotune.active))
check(f"finished all trials ({s.autotune.trial}/{len(s.autotune.order)})", done and not s.autotune.active)
check(f"went through every phase ({sorted(phases)})", {"to_start", "topup", "timing", "finishing"} <= phases)
check("every trial began and ended at the loop's first room", starts and all(r == loop.steps[0].room for r in starts))
check("best one kept, baseline cleared", not st.tune_baseline and s.autotune.last_results())
print("\n".join(l for l in s.logs if "Auto-tune" in l)[-1500:])
print("ALL PASS" if ok else "SOME FAILED")
os._exit(0 if ok else 1)
