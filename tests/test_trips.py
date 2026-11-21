"""Bank and shop trips at the end of a lap."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.shoptrips import buy_rules
st = config.Settings(); st.save = lambda: None; st.board = "Paradigm"
s = Session(st); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
b, w, T = s.bot, s.world, s.trips
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
check("buy rules parse", buy_rules("healing potion 3-10; torch 2-5") == [("healing potion", 3, 10), ("torch", 2, 5)])
check(f"banks from MME ({len(T.banks())})", (1, 297) in T.banks())
class P:
    title = "My loop"; steps = []; is_loop = True; resolved = True
loop = P()
s.state.candidates = [(1, 300)]
b.plan_route = lambda a, c, ask=None: [1] * (3 if c == (1, 297) else 50)
calls = []
b.goto = lambda room, then=None, ask=None: calls.append(("goto", room)) or True
b.start_path = lambda mp, loop=None, checked=False: calls.append(("loop", mp.title)) or True
s.state.wealth = 50000
check("deposit off → no trip", not T.lap_end(loop))
st.auto_deposit_on = True; st.deposit_at_copper = 100000
check("under the amount → no trip", not T.lap_end(loop))
s.state.wealth = 250000
check(f"over the amount → off to the nearest bank ({calls})", T.lap_end(loop) and calls[-1] == ("goto", (1, 297)))
s.state.candidates = [(1, 297)]; b.walking = False
T.tick(); T.trip["next_at"] = 0; T.tick()
check(f"at the bank → deposits ({sent})", sent and sent[-1] == "deposit 250000")
T.trip["next_at"] = 0; T.tick()            # 'i' to see what you carry now…
T.trip["next_at"] = 0; T.tick()            # …then back
check(f"then back to the loop ({calls})", calls[-1] == ("loop", "My loop") and T.trip is None)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
