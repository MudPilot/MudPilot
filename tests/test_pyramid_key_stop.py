"""PVE, 2026-10-30, Great Pyramid 12/2005: 'a key' then MudPilot sent 'bre' — 'Only floating key left — nothing to kill;
breaking combat' (Dan: very few reasons except sneak and hide to break combat). Then, after Stop/Rego on the golden lion
key detour, it got the key and stood there: Rego had resumed only 'Go to 12/2005', the Pharoah (12/2085) forgotten."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.megamud_files import MPath
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object(); s._connected_at = time.time() - 60
b, g = s.bot, s.state
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


key = s.world.monster_names["floating key"]
g.candidates = [(12, 2005)]
g.view = RoomView("Great Pyramid", {"N", "S", "E", "W"}, [("floating key", key)], [], [], time.time()); g.view_seq += 1
g.in_combat = True
g.hp, g.max_hp, g.ma, g.max_ma = 585, 674, 489, 489
g.last_prompt = time.time()
b.tick()
check(f"in combat with the floating key: no 'bre' ({sent})", "bre" not in sent)
check("the sphinx still counts as unkillable", b._unkillable(s.world.monster_names["stone sphinx"]))
# Stop on the key detour: Rego goes on to the Pharoah
pharoah = MPath("Go to 12/2085 Great Pyramid", "MudPilot", "", "")
b.errands.active = {"todo": [], "then": (pharoah, False), "after": None, "target": (12, 2085)}
b.walking, b.path = True, MPath("Go to 12/2005 Great Pyramid", "MudPilot", "", "")
b.stop("Stopped by you")
check(f"Rego carries on to 12/2085 ({b.resume and b.resume.get('target')})",
      b.resume and b.resume.get("target") == (12, 2085) and b.resume["path"] is pharoah)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
