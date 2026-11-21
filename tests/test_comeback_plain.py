"""@comeback without a room (MegaMUD sends it bare — Dan, 2026-11-02: "there will be a lot of players still on
megamud"), @comeback / @summon invite on arrival, a typed bare @comeback carries our room, and a follower whose
leader logged off first still rejoins that leader after its restart (Buddy got left)."""
import os, sys, time, json, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object(); s._connected_at = time.time() - 60
sent = []
s.telnet.send_line = lambda c: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g, cb, r = s.state, s.comeback, s.remote
g.candidates = [(17, 1638)]
g.party = {"Evolution": {}}
# bare @comeback from Buddy (not in the party): @where him, then search our trail — no "needs map and room"
msg = r.c_comeback("Buddy", "")
check(f"bare @comeback accepted ({msg})", msg and "needs" not in msg)
check(f"…asks @where ({sent})", any(c.lower() == "/buddy @where" for c in sent))
check("…a fetch is on, inviting at the end", cb.fetch and cb.fetch["name"] == "Buddy" and not cb.fetch.get("no_invite"))
# with a room: going there, then invite on arrival
cb.fetch = None; sent.clear()
r._goto_bg = lambda who, key, where: f"walking to {where}"
msg = r.c_comeback("Buddy", "17 1640")
check(f"room @comeback: coming ({msg})", "coming to 17/1640" in msg and cb.fetch["phase"] == "going"
      and cb.fetch["room"] == (17, 1640))
check("…no @where for that one", not any("@where" in c for c in sent))
g.candidates = [(17, 1640)]; s.bot.walking = False
cb.fetch["t"] = time.time()
cb.tick()
cb.tick()
check(f"arrived: invites Buddy ({sent})", "invite Buddy" in sent)
# @summon: arrived → invite
sent.clear(); cb.fetch = None
r._summon = {"by": "Revolution", "to": (17, 1640), "channel": "telepath", "t": time.time() - 10}
r._summon_tick()
check(f"summoned and there: invites them ({sent})", "invite Revolution" in sent)
# typed '/Evolution @comeback' on Buddy's side carries his room
sent.clear()
s.send("/Buddy @comeback")
check(f"typed bare @comeback gets our room ({sent})", any(c.endswith("@comeback 17 1640") for c in sent))
# follower restart: leader @stopped and logged off before we saved the resume
s2 = Session(config.Settings(), world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db"))
s2.settings.save = lambda: None; s2.settings.my_name = "Buddy"; s2._no_log_file = True
c = s2.control
c.dir = tempfile.mkdtemp()
s2.bot.x._following = None
c._leader_stopped = "Evolution"
check(f"leader stays known after they logged off ({c._leader()})", c._leader() == "Evolution")
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
