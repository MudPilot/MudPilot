"""Dan, 2026-11-17: Miserable was training in Rodolfo's Training Hall (14/1792, in through a 80,000-copper toll east
from 14/1791). The party kept breaking, he asked Revolution '@comeback 14/1792' and Revolution walked in four times,
8 runic a go. Not ignored: Revolution stops outside the toll and @summons him out."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from types import SimpleNamespace
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st); s._no_log_file = True
sent, logs = [], []
s.send = lambda x, from_bot=False, **k: sent.append(x)
_log = s.log
s.log = lambda m, *a, **k: logs.append(m) or _log(m, *a, **k)
b, c = s.bot, s.comeback
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
HALL, OUTSIDE = (14, 1792), (14, 1791)
s.world.char = {**(s.world.char or {}), "wealth": 50_000_000}   # rich enough for the toll
s.world.forget_routes()
start = next(e.to for e in s.world.room(OUTSIDE).exits.values() if tuple(e.to) != HALL)
s.state.candidates = [tuple(start)]
s.state.party = {"Revolution": {}}
calls = []
def goto(room, then=None, ask=None):
    calls.append(room); b.walking = True; b._goto_target = room
    return True
b.goto = goto
ts = c.toll_stop(HALL)
check(f"toll_stop: outside the hall at 14/1791, 80,000 copper ({ts})", ts == (OUTSIDE, 80000))
r = s.remote.c_comeback("Miserable", "14/1792")
check(f"@comeback 14/1792: walks to 14/1791, not into the hall ({calls}; '{r}')", calls == [OUTSIDE])
check(f"…and @summons Miserable out to 14/1791 ({sent})", "/Miserable @summon 14 1791" in sent)
# there, he isn't out yet: wait, don't walk in
s.state.candidates = [OUTSIDE]; b.walking = False; calls.clear(); sent.clear()
s.state.view = SimpleNamespace(players=[], monsters=[], items=[])
c.tick()
check(f"outside, he's not out yet: waiting, no walk in ({calls}, {sent})", not calls and not any("invite" in x for x in sent))
# he walks out: invite him
s.state.view = SimpleNamespace(players=["Miserable"], monsters=[], items=[])
c.tick(); c.tick()
check(f"he's out: invited ({sent})", any(x == "invite Miserable" for x in sent))
# no toll on the way: walks straight there as before
c.fetch = None; calls.clear(); sent.clear()
s.state.candidates = [tuple(start)]; s.state.view = SimpleNamespace(players=[], monsters=[], items=[])
s.remote.c_comeback("Miserable", f"{OUTSIDE[0]}/{OUTSIDE[1]}")
time.sleep(1.5)
check(f"no toll: no @summon ({sent})", not any("@summon" in x for x in sent))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
