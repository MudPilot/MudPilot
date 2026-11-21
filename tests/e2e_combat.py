"""Combat test: forces a fire-resistant mob into the start room, casts with auto-switch."""
import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
PORT = int(os.environ.get("PORT", 2410))
world = WorldDB(config.WORLD_DB)
sim = simserver.Sim(world, seed=3, mob_rate=0)
hh = world.monster_names["hellhound"]; z = world.monster_names["zombie"]
sim.mobs[(1, 1)] = [dict(hh), dict(z)]
def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r, w: simserver.handle(sim, r, w), "127.0.0.1", PORT)
        async with srv: await srv.serve_forever()
    asyncio.run(go())
threading.Thread(target=run_server, daemon=True).start(); time.sleep(0.4)
st = config.Settings(); st.host, st.port, st.username = "127.0.0.1", PORT, "Tester"
st.auto_combat = True; st.attack_spells = ["fbal", "bliz", "lbol"]; st.auto_rest = False
st.min_mobs, st.max_mobs = int(os.environ.get("MIN", 1)), int(os.environ.get("MAX", 3))
s = Session(st); s.password = "x"; s.connect()
end = time.time() + float(os.environ.get("SECS", 40))
while time.time() < end and not (s.state.kills >= 2):
    s.poll(); time.sleep(0.03)
print("kills", s.state.kills, "exp", s.state.exp_gained, "| info:", s.bot.spell_info)
print("observed:", {(world.monsters[k[0]]['name'], world.spells[k[1]]['Name']): v for k, v in s.spellbook.observed.items()})
print("\n".join(l for l in s.logs if "Switch" in l or "Trigger" not in l)[-1500:])
