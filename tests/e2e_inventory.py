import asyncio, os, sys, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
from mudpilot.ansi import Style
PORT = 2470
world = WorldDB(config.WORLD_DB); sim = simserver.Sim(world, seed=3, mob_rate=0)
def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r, w: simserver.handle(sim, r, w), "127.0.0.1", PORT)
        async with srv: await srv.serve_forever()
    asyncio.run(go())
threading.Thread(target=run_server, daemon=True).start(); time.sleep(0.4)
st = config.Settings(); st.host, st.port, st.username = "127.0.0.1", PORT, "Tester"
st.remote_players = {"Miserable": ["query", "inventory"], "Bob": ["query"]}
st.save = lambda: None
s = Session(st); s.password = "x"; s.connect()
sent = []
s.on_sent = lambda c, b: sent.append(c) if c.startswith(("/", "i")) else None
def run(secs):
    end = time.time() + secs
    while time.time() < end: s.poll(); time.sleep(0.03)
run(2)
s._line([("Miserable telepaths: @inventory", Style())]); run(2)
s._line([("Bob telepaths: @inv", Style())]); run(1)
for x in sent: print(x)
