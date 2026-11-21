"""Headless end-to-end: practice server + Session; checks tracking, goto, paths, combat."""
import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
from mudpilot.megamud_files import path_from_route, write_mp, read_mp, resolve_path

PORT = int(os.environ.get("PORT", 2399))
world = WorldDB(config.WORLD_DB)
sim = simserver.Sim(world, seed=7, mob_rate=float(os.environ.get("MOBS", "0")))

def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r, w: simserver.handle(sim, r, w), "127.0.0.1", PORT)
        async with srv:
            await srv.serve_forever()
    asyncio.run(go())
threading.Thread(target=run_server, daemon=True).start()
time.sleep(0.5)

st = config.Settings()
st.host, st.port, st.username = "127.0.0.1", PORT, "Tester"
st.auto_reconnect = False
s = Session(st)
s.password = "secret"
mism = []
def on_room(gs):
    true = sim.players[-1].room if sim.players else None
    if gs.room != true:
        mism.append((gs.room, true, list(gs.candidates)[:3], gs.view.name if gs.view else None))
s.state.on_room.append(on_room)
s.connect()

def run(secs, until=None):
    end = time.time() + secs
    while time.time() < end:
        s.poll()
        if until and until():
            return True
        time.sleep(0.03)
    return False

run(3, lambda: s.state.room is not None)
print("start room:", s.state.room_label)
target = tuple(int(x) for x in os.environ.get("TARGET", "3/606").split("/"))
ok = s.bot.goto(target)
print("goto started:", ok, s.bot.path.title if s.bot.path else None, len(s.bot.path.steps) if s.bot.path else 0)
arrived = run(float(os.environ.get("SECS", 120)), lambda: not s.bot.walking)
print("arrived:", arrived, "tracked:", s.state.room, "true:", sim.players[-1].room, "steps:", s.state.steps_walked)
print("status:", s.bot.status, "| exp:", s.state.exp_gained, "kills:", s.state.kills, "hp:", s.state.hp, "/", s.state.max_hp)
print("mismatches:", len(mism), mism[:5])
print("\n".join(s.logs[-12:]))
