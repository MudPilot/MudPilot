"""Dan, 2026-11-01: '@goto bank of godfrey' without the room numbers — the Goto list's names (Rooms.md places, MME's
shops and NPCs) are what people remember. One place → go there; several different places → say which."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.state.candidates = [(1, 2402)]
s.known_rooms = lambda: [("Silvermere", "Bank of Godfrey-1 297", (1, 297)),
                         ("Aldreth", "Tree House (Aldreth) (12-20)-1 2305", (1, 2305))]
s.remote._goto_bg = lambda sender, key, where: f"walking to {where}"
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


g = lambda q: s.remote.c_goto("Dan", q)
check(f"bank of godfrey ({g('bank of godfrey')})", "(1/297)" in g("bank of godfrey"))
check(f"part of a name ({g('bank of go')})", "(1/297)" in g("bank of go"))
check(f"your Rooms.md place beats a room of the same name ({g('tree house')})", "(1/2305)" in g("tree house"))
check(f"room numbers still work ({g('17 1626')})", "(17/1626)" in g("17 1626"))
check(f"monsters still work ({g('wraithlord')})", "(3/650)" in g("wraithlord"))
check(f"several different places: asks which ({g('mayor')})", "say which" in g("mayor"))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
