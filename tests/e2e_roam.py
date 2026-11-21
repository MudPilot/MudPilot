"""Auto-roam on the practice server: wanders, fights, keeps tracking."""
import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
PORT = 2450
world = WorldDB(config.world_path("Main"))
sim = simserver.Sim(world, seed=5, mob_rate=0.2)
def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r, w: simserver.handle(sim, r, w), "127.0.0.1", PORT)
        async with srv: await srv.serve_forever()
    asyncio.run(go())
threading.Thread(target=run_server, daemon=True).start(); time.sleep(0.4)
st = config.Settings(); st.save = lambda: None
st.host, st.port, st.username = "127.0.0.1", PORT, "Tester"
st.auto_combat = True; st.auto_rest = True; st.default_task = "roam"; st.roam_dirs = ["N", "S", "E", "W"]
s = Session(st); s.password = "x"
mism, rooms = [], set()
s.state.on_room.append(lambda gs: (rooms.add(gs.room), mism.append((gs.room, sim.players[-1].room))
                                   if gs.room and gs.room != sim.players[-1].room else None))
s.connect()
end = time.time() + 60
while time.time() < end:
    s.poll(); time.sleep(0.03)
print(f"roamed through {len(rooms)} rooms, kills {s.state.kills}, mismatches {len(mism)}")
print("ALL PASS" if len(rooms) >= 8 and not mism else "SOME FAILED")
