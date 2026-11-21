"""No attack spells configured: the bot reads `spells`, then picks per mob (fire-resistant mob gets no fire)."""
import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
PORT = int(os.environ.get("PORT", 2500))
world = WorldDB(config.WORLD_DB)
sim = simserver.Sim(world, seed=3, mob_rate=0)
if os.environ.get("CLASS"):
    from mudpilot.spells import class_spells
    sim.known = class_spells(world, next(k for k, v in world.classes.items() if v["Name"] == os.environ["CLASS"]), 30)
M = world.monster_names
# a fire-resistant mob in the start room, a fire-weak one next door (1/3 is north)
sim.mobs[(1, 1)] = [dict(M["hellhound"])]
sim.mobs[(1, 3)] = [dict(M["zombie"])]
def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r, w: simserver.handle(sim, r, w), "127.0.0.1", PORT)
        async with srv: await srv.serve_forever()
    asyncio.run(go())
threading.Thread(target=run_server, daemon=True).start(); time.sleep(0.4)
st = config.Settings(); st.host, st.port, st.username = "127.0.0.1", PORT, "Tester"
st.auto_combat = True; st.attack_spells = []; st.auto_spells = True; st.auto_rest = False; st.char_level = int(os.environ.get("LEVEL", 38))
st.save = lambda: None
s = Session(st); s.password = "x"; s.connect()
casts = []
s.on_sent = lambda c, b: casts.append(c) if c.split() and c.split()[0] in {x["Short"] for x in sim.known} or c == "spells" else None
def run(sec, until=None):
    end = time.time() + sec
    while time.time() < end:
        s.poll(); time.sleep(0.03)
        if until and until(): return
run(25, lambda: s.state.kills >= 1)
s.send("north")
run(25, lambda: s.state.kills >= 2)
print("known spells read:", len(st.known_spells), "| kills", s.state.kills)
print("casts:", sorted(set(casts)))
for l in s.logs:
    if "Switch" in l or "Spell list" in l: print(l)
