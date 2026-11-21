"""Pre/post rest gear swaps + party check, on the practice server."""
import asyncio, os, sys, threading, time
os.environ["SIM_PARTY"] = "1"
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import simserver, config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
from mudpilot.megamud_files import path_from_route
PORT = 2440
world = WorldDB(config.WORLD_DB if hasattr(config, "WORLD_DB") else config.world_path("Main"))
sim = simserver.Sim(world, seed=11, mob_rate=0.35)
def run_server():
    async def go():
        srv = await asyncio.start_server(lambda r, w: simserver.handle(sim, r, w), "127.0.0.1", PORT)
        async with srv: await srv.serve_forever()
    asyncio.run(go())
threading.Thread(target=run_server, daemon=True).start(); time.sleep(0.4)
st = config.Settings(); st.save = lambda: None
st.host, st.port, st.username = "127.0.0.1", PORT, "Tester"
st.auto_combat = True; st.attack_spells = ["bliz", "fbal"]; st.min_mobs, st.max_mobs = 1, 3
st.auto_rest = True; st.rest_below_ma, st.rest_until_ma = 60, 90; st.use_meditate = True
st.rest_swap_on = st.med_swap_on = True
st.mana_throttle = False; st.stop_before_boss = False   # this test wants it to sit down and meditate
st.pre_rest_cmd = "eq sparkling ring^Mremove platinum ring"; st.post_rest_cmd = "eq platinum ring"
st.pre_med_cmd = "eq rainbow robes^M"; st.post_med_cmd = "eq woodland robes"
st.party_check_secs = 5; st.party_wait_pct = 0; st.attack_good = st.attack_neutral = True   # this test is about gear swaps, so let it fight anything
s = Session(st); s.password = "x"
sent = []
s.on_sent = lambda c, b: sent.append((time.time(), c))
s.connect()
t0 = time.time()
while time.time() - t0 < 3: s.poll(); time.sleep(0.03)
loop = path_from_route(world, (1, 1), world.route((1, 1), (1, 16)) + world.route((1, 16), (1, 1)), name="test loop")
s.bot.start_path(loop)
end = time.time() + 110
while time.time() < end:
    s.poll(); time.sleep(0.03)
cmds = [c for _t, c in sent]
moves = {"n", "s", "e", "w", "ne", "nw", "se", "sw", "u", "d", "north", "south", "east", "west", "northeast", "northwest", "southeast", "southwest", "up", "down"}
ok = True
pres = [i for i, c in enumerate(cmds) if c in ("eq sparkling ring", "eq rainbow robes")]
print("rests/meds:", sum(c in ("rest", "medi", "meditate") for c in cmds), "| pre swaps:", len(pres),
      "| post swaps:", sum(c in ("eq platinum ring", "eq woodland robes") for c in cmds))
for i in pres:
    rest = next((j for j in range(i, len(cmds)) if cmds[j] in ("rest", "medi", "meditate")), None)
    post = next((j for j in range(i, len(cmds)) if cmds[j] in ("eq platinum ring", "eq woodland robes")), None)
    move = next((j for j in range(i, len(cmds)) if cmds[j] in moves or cmds[j].startswith(("attack", "a ", "cast", "bliz", "fbal"))), None)
    good = rest is not None and (move is None or (post is not None and post < move))
    ok &= good
    print(" swap at", i, "rest", rest, "post", post, "next move/attack", move, "OK" if good else "BAD")
print("party:", {k: (v["hp"], v["ma"], v["rank"]) for k, v in s.state.party.items()}, "| par sent:", cmds.count("par"))
ok &= len(s.state.party) == 3 and bool(pres)
print("\n".join(s.logs[-15:])); print("ALL PASS" if ok else "SOME FAILED")
