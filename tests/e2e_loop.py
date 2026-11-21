import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
from mudpilot.megamud_files import path_from_route
PORT = 2430
world = WorldDB(config.WORLD_DB); sim = simserver.Sim(world, seed=11, mob_rate=0.35)
def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r, w: simserver.handle(sim, r, w), "127.0.0.1", PORT)
        async with srv: await srv.serve_forever()
    asyncio.run(go())
threading.Thread(target=run_server, daemon=True).start(); time.sleep(0.4)
st = config.Settings(); st.host, st.port, st.username = "127.0.0.1", PORT, "Tester"
st.auto_combat = True; st.attack_spells = ["bliz", "fbal"]; st.min_mobs, st.max_mobs = 1, 3
st.auto_rest = True; st.rest_below_ma, st.rest_until_ma = 30, 90; st.auto_loot = True
s = Session(st); s.password = "x"
mism = []
s.state.on_room.append(lambda gs: mism.append((gs.room, sim.players[-1].room)) if gs.room and gs.room != sim.players[-1].room else None)
s.connect()
t0 = time.time()
while time.time() - t0 < 3: s.poll(); time.sleep(0.03)
loop = path_from_route(world, (1, 1), world.route((1, 1), (1, 16)) + world.route((1, 16), (1, 1)), name="test loop")
s.bot.start_path(loop)
end = time.time() + 120
laps, last = 0, 0
while time.time() < end:
    s.poll(); time.sleep(0.03)
    if s.bot.idx < last: laps += 1
    last = s.bot.idx
print(f"loop {len(loop.steps)} steps, laps {laps}, idx {s.bot.idx}, walked {s.state.steps_walked}")
print(f"kills {s.state.kills} exp {s.state.exp_gained} cash {s.state.copper_looted} deaths {s.state.deaths}")
print("tracking mismatches:", len(mism), mism[:3], "| walking:", s.bot.walking, "|", s.bot.status)
print("\n".join(l for l in s.logs if "Trigger" not in l)[-900:])
