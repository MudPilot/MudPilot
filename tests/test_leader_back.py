"""Dan, 2026-10-29: Buddy follows Revolution (MegaMUD). Revolution dropped and came back; Buddy stood in the same room
for 8 minutes waiting to be invited. When the leader we follow comes back: '/Revolution @invite', join, '@rego'."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
st.auto_combat = st.auto_rest = st.auto_bless = st.auto_heal = False
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g, x = s.state, s.bot.x
x._following = "Revolution"
s._connected_at = time.time() - 60
feed = lambda t: s._line([(t, Style())])
feed("Revolution just disconnected!!!")
g.party = {}
check("leader gone noticed", x._leader_gone_since)
feed("Revolution just entered the Realm.")
check("a rejoin is set up", getattr(s, "_rejoin", None) and s._rejoin["leader"] == "Revolution")
from mudpilot.gamestate import RoomView
g.view = RoomView("Dark Corridor", {"S"}, [], [], ["Revolution"], time.time())   # he shows up in our room
sent.clear()
s._rejoin_tick()
check(f"he's here: asks for an invite straight away ({sent})", "/Revolution @invite" in sent and "/Revolution @rego" not in sent)
g.party = {"Revolution": {}, "Buddy": {}}       # joined (players.py joins on their invite)
sent.clear(); s._rejoin_tick()
check(f"…then @rego ({sent})", "/Revolution @rego" in sent and not getattr(s, "_rejoin", None))
# 2026-10-30: back in at 8/899 with Revolution at 8/16 — 'You don't see buddy here.' 22 times. Not in the same
# room: ask where they are and walk there first
from mudpilot.gamestate import RoomView
s._rejoin = {"leader": "Revolution", "t": time.time(), "asked": time.time() - 15, "tries": 1, "joined": False}
g.party = {}
x._following = ""                                  # (relogged: not following anyone yet)
g.candidates = [(8, 899)]
g.view = RoomView("Dark Tunnel", {"N"}, [], [], ["Evolution"], time.time())
sent.clear(); s._rejoin_tick()
check(f"leader not here: asks @where first, no @invite ({sent})",
      "/Revolution @where" in sent and "/Revolution @invite" not in sent)
check("…and goes to them (comeback, no invite of its own)", s.comeback.fetch and s.comeback.fetch.get("no_invite"))
s.comeback.fetch = None
g.view = RoomView("Dark Corridor", {"S"}, [], [], ["Revolution Medi", "Evolution"], time.time())
sent.clear(); s._rejoin["asked"] = time.time() - 30; s._rejoin_tick()
check(f"in the same room: asks for the invite ({sent})", "/Revolution @invite" in sent)
sent.clear(); s._rejoin_tick()
check(f"…and not again within 30 s ({sent})", "/Revolution @invite" not in sent)
# 2026-10-30: Buddy, dead in the temple, asked Revolution (a map away) for an invite every 15 s and @where every
# minute. Not in his room: no @invite. Dead (held): no @where either — he can't walk there
g.view = RoomView("Temple, Halls of the Dead", {"U"}, [], [], [], time.time())
s.bot.dead_hold = time.time()
s.comeback.fetch = None; s._rejoin["went"] = 0; s._rejoin["asked"] = 0
sent.clear(); s._rejoin_tick(); s._rejoin_tick()
check(f"dead, leader elsewhere: no @invite, no @where ({sent})", not any("@invite" in x or "@where" in x for x in sent))
s.bot.dead_hold = 0
g.view = RoomView("Dark Corridor", {"S"}, [], [], ["Revolution Medi", "Evolution"], time.time())
# the walk to the leader left a 'Rego carries on to …' behind (0.8.115): back in their party, it's cleared
s.bot.resume = {"path": None, "loop": False, "after": None, "target": (1, 2342)}
g.party = {"Revolution": {}, "Buddy": {}}
sent.clear(); s._rejoin_tick()
check(f"back in: @rego them, and nothing of ours left to Rego ({sent}, {s.bot.resume})",
      "/Revolution @rego" in sent and not s.bot.resume)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
