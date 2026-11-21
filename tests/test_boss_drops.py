"""Dan, 2026-11-03: after a boss hunt kill, pick up what the boss drops — not everyone get-all, and not chests
(they're heavy). The crimson mist drops the emerald-tipped crozier (MME, 7%)."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"; st.boss_loot_cmd = ""
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
mist = s.world.monsters[309]
drops = [n for n, _p in s.combatlog.mme_drops(mist)]
check(f"MME's drop list for the mist ({drops})", "emerald-tipped crozier" in [d.lower() for d in drops])
s.combatlog.seen_drops = lambda name: (3, {"small chest": 1})    # once dropped a chest
s.state.view = RoomView("Ancient Ruin", {"N"}, [], [(1, "emerald-tipped crozier"), (1, "small chest"),
                                                    (1, "log raft"), (3000, "gold crowns")], [], time.time())
got = s.bosshunt.grab_drops(309)
check(f"picks up the crozier, not the chest, the raft or the coins ({sent})",
      sent == ["get emerald-tipped crozier"] and got == ["emerald-tipped crozier"])
# in the hunt: killed → look, then get
bh = s.bosshunt
s.bosses.save = lambda: None
s.bosses.rec(mist)
bh.active = {"num": 309, "name": "crimson mist", "room": (3, 560), "dead_since": 0, "back": None, "from": None,
             "t": time.time(), "arrived": time.time(), "killed": 0, "sweep": [], "lairs": 16, "trip": 0}
s.bosses.data["309"]["dead_since"] = time.time()
s.state.in_combat = False
sent.clear()
bh._follow_up()
check(f"killed: looks at the floor first ({sent})", sent == [""])
bh.active["killed"] -= 3
bh._follow_up()
check(f"…then gets the drop ({sent})", "get emerald-tipped crozier" in sent and "get small chest" not in sent)
# killed on a loop (no hunt): the same — look, then get its drops
bh.active = None
s.telnet = type("T", (), {"connected": True, "send_line": lambda self, x: None, "close": lambda self: None})()
s._entered = True
st.boss_hunt_on = False
sent.clear()
bh.after_kill(309)
bh._loot_tick()
check(f"loop kill: looks ({sent})", sent == [""])
bh._loot["looked"] -= 3
bh._loot_tick()
check(f"…then gets the crozier ({sent})", sent == ["", "get emerald-tipped crozier"])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
