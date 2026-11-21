"""Teleport into a room whose name is shared by hundreds of rooms; the bot types `pro` and knows where it is."""
import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
PORT = int(os.environ.get("PORT", 2540))
world = WorldDB(config.WORLD_DB)
sim = simserver.Sim(world, seed=4, mob_rate=0)
def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r, w: simserver.handle(sim, r, w), "127.0.0.1", PORT)
        async with srv: await srv.serve_forever()
    asyncio.run(go())
threading.Thread(target=run_server, daemon=True).start(); time.sleep(0.4)
st = config.Settings(); st.host, st.port, st.username = "127.0.0.1", PORT, "Tester"
st.auto_combat = False; st.auto_rest = False; st.save = lambda: None; st.auto_spells = False
s = Session(st); s.password = "x"; s.connect()
def run(sec, until=None):
    end = time.time() + sec
    while time.time() < end:
        s.poll(); time.sleep(0.03)
        if until and until(): return True
    return False
run(3, lambda: s.state.room is not None)
target = sorted(world.by_name["stone tunnel"])[400]          # 900+ rooms share this name
sim.players[-1].room = target
s.send("")                                                     # we see the room but can't place it yet
run(2)
print("after look:", len(s.state.candidates), "candidates")
ok = run(12, lambda: s.state.room == target)
print("located:", ok, s.state.room, "true:", target, "| cmd sent:", [l for l in s.logs if "confirmed" in l][-1:])
