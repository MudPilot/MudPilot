import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
PORT = 2420
world = WorldDB(config.WORLD_DB); sim = simserver.Sim(world, seed=3, mob_rate=0)
def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r, w: simserver.handle(sim, r, w), "127.0.0.1", PORT)
        async with srv: await srv.serve_forever()
    asyncio.run(go())
threading.Thread(target=run_server, daemon=True).start(); time.sleep(0.4)
st = config.Settings(); st.host, st.port, st.username = "127.0.0.1", PORT, "Tester"
st.abil_check_cmd, st.abil_check_secs = "abil", 10
st.buffs = [{"name": "Nature tap", "cast": "ntap", "check_cmd": "abil 145", "ability": "145", "source": "spells",
             "op": ">=", "value": int(os.environ.get("TARGET", 150)), "check_secs": 20, "max_rerolls": 8, "min_mana_pct": 10, "enabled": True}]
s = Session(st); s.password = "x"; s.connect()
casts = []
s.on_sent = lambda c, b: casts.append((round(time.time() % 1000, 1), c)) if c in ("ntap", "nity", "flux", "abil 145") else None
end = time.time() + float(os.environ.get("SECS", 30))
while time.time() < end:
    s.poll(); time.sleep(0.03)
print(casts)
print("SC spells:", s.state.abil_value("SpellCasting", "spells"), "| 145 spells:", s.state.abil_value(145, "spells"), "| 145 total:", s.state.abil_value(145, "total"))
print("status:", [s.bot.buff_status(b) for b in st.buffs])
print("\n".join(l for l in s.logs if "Casting" in l))
