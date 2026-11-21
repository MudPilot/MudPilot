"""Evolution, 2026-11-01: at 3024/3024 encumbrance it kept trying every pile of gold ("picked up 0 gold crown") —
full means no coins, anywhere, until there's room again."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"; st.loot_cash = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
b, g = s.bot, s.state
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


g.candidates = [(8, 497)]
g.enc = (3024, 3024, "Heavy", 100)
g.view = RoomView("Dark Corridor", {"N"}, [], [(40, "gold crowns")], [], time.time())
g.view_seq += 1
sent.clear(); b.loot()
check(f"full: the gold is left ({sent})", not any("gold" in c for c in sent))
g.enc = (2000, 3024, "Medium", 66)
g.view_seq += 1
sent.clear(); b._looted_seq = -1; b.loot()
check(f"room again: picks it up ({sent})", any("gold" in c for c in sent))
# Dan, 2026-11-07: an option (off by default) — no coins once you're Heavy
st.coins_not_heavy, st.coins_heavy_pct, st.drop_small_coins = True, 66, False
g.enc = (2100, 3024, "Heavy", 69)
g.view_seq += 1
sent.clear(); b._looted_seq = -1; b._loot_wait = None; b.loot()
check(f"Heavy with the option on: gold left ({sent})", not any("gold" in c for c in sent))
g.enc = (1800, 3024, "Medium", 59)
g.view_seq += 1
sent.clear(); b._looted_seq = -1; b._loot_wait = None; b.loot()
check(f"under the line: picks it up ({sent})", any("gold" in c for c in sent))
st.coins_not_heavy = False
g.enc = (2100, 3024, "Heavy", 69)
g.view_seq += 1
sent.clear(); b._looted_seq = -1; b._loot_wait = None; b.loot()
check(f"option off: Heavy still picks up ({sent})", any("gold" in c for c in sent))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
