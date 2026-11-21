"""A loop is running; a timer event hunts a boss (depraved murderer, 21 steps away), then the loop resumes."""
import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
from mudpilot.megamud_files import path_from_route
from mudpilot import bosses as B
B.BOSS_FILE_OVERRIDE = "/tmp/claude-0/bosses_evt.json"
if os.path.exists(B.BOSS_FILE_OVERRIDE): os.remove(B.BOSS_FILE_OVERRIDE)
PORT = int(os.environ.get("PORT", 2530))
world = WorldDB(config.WORLD_DB)
sim = simserver.Sim(world, seed=4, mob_rate=0)
boss = world.boss_named("depraved murderer")
spawn = tuple(boss["spawn_rooms"][0])
sim.mobs[spawn] = [dict(boss)]
def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r, w: simserver.handle(sim, r, w), "127.0.0.1", PORT)
        async with srv: await srv.serve_forever()
    asyncio.run(go())
threading.Thread(target=run_server, daemon=True).start(); time.sleep(0.4)
st = config.Settings(); st.host, st.port, st.username = "127.0.0.1", PORT, "Tester"
st.auto_combat = False          # combat off: the hunt must still fight the boss
st.auto_rest = False; st.save = lambda: None
st.events = [{"name": "Murderer run", "enabled": True, "when": "timer", "every": 0.25,
              "do": "hunt", "boss": "depraved murderer", "not_fighting": True, "min_hp": 0}]
s = Session(st); s.password = "x"; s.connect()
trail = []
s.state.on_room.append(lambda gs: trail.append(gs.room) if gs.room and (not trail or trail[-1] != gs.room) else None)
def run(sec, until=None):
    end = time.time() + sec
    while time.time() < end:
        s.poll(); time.sleep(0.03)
        if until and until(): return True
    return False
run(3, lambda: s.state.room is not None)
w = s.world
loop = path_from_route(w, (1, 1), w.route((1, 1), (1, 16)) + w.route((1, 16), (1, 1)), name="Town loop")
s.bot.start_path(loop)
run(90, lambda: s.events.hunt is None and s.state.kills >= 1 and s.bot.walking and s.bot.path is loop)
run(6)
print("boss killed:", s.state.kills >= 1, "| reached spawn", spawn, ":", spawn in trail,
      "| back on loop:", s.bot.walking and s.bot.path is loop, "| step", s.bot.idx, "| room", s.state.room)
print("boss timer:", s.bosses.status(boss["num"])[0])
for l in s.logs:
    if "Event" in l or "Walking" in l or "Boss" in l: print(l)
