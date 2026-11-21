"""Record a real (simulated) session, then replay the recording offline: MudPilot should send the same
commands — that's what makes a recording from Dan's PC reproducible here."""
import asyncio, os, sys, tempfile, threading, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.pop("MUDPILOT_NO_RECORD", None)
from mudpilot import simserver, config, recorder
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
tmp = tempfile.mkdtemp()
recorder.trace_dir = lambda: tmp
PORT = int(os.environ.get("PORT", 2433))
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
st.save = lambda: None
st.auto_combat = True; st.attack_spells = ["fbal", "bliz", "lbol"]; st.auto_rest = False
s = Session(st); s.password = "x"; s.connect()
end = time.time() + 40
while time.time() < end and not (s.state.kills >= 2):
    s.poll(); time.sleep(0.03)
path = s.recorder.flush_now(); time.sleep(0.3); s.recorder.flush_now()
s.telnet.close()
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
check("the session was recorded", path and os.path.getsize(path) > 1000)
from mudpilot import replay
recs = replay.load(path)
res = replay.run(recs)
rec_cmds = [c for _t, c in res["recorded"] if c.strip()]
rep_cmds = [c for _t, c in res["sent"] if c.strip()]
print("recorded:", rec_cmds[:20]); print("replay:  ", rep_cmds[:20])
import difflib
ratio = difflib.SequenceMatcher(a=rec_cmds, b=rep_cmds).ratio()
check(f"replay sends (nearly) the same commands ({ratio:.0%})", ratio >= 0.8)
check("…including the spells", any(c.startswith(("fbal", "bliz", "lbol")) for c in rep_cmds))
for mode in ("lines", "blob"):
    r2 = replay.run(recs, rechunk=mode)
    c2 = [c for _t, c in r2["sent"] if c.strip()]
    check(f"same commands when the text arrives {'a line at a time' if mode == 'lines' else 'all at once'}",
          difflib.SequenceMatcher(a=rep_cmds, b=c2).ratio() >= 0.9)
for x in replay.diff(res, 3):
    print("  diff:", x["op"], x["recorded"], "→", x["replay"])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
