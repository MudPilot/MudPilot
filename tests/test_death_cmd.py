"""Dan, 2026-10-30:
- '@death' answers with the last 3 deaths — from the 'Recent Deaths' rows at the bottom of 'pro'.
- A follower back from a restart doesn't walk off on its own: Miserable came back while Revolution was dead in the
  temple, couldn't get to him, and went looping the Glades solo. What it was walking waits for its leader."""
import os, sys, time, json, tempfile
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
r = s.remote
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


r._channel = "telepath"
check("@death asks the board ('pro')", r.c_death("Dan", "") is None and sent and sent[-1] in ("pro", st.locate_cmd.strip()))
t0 = time.time()
rows = ["Recent Deaths:", "10/20/2026 6:20 AM - grimhound - 13/2925", "10/12/2026 3:57 PM - Suicide - 1/2189",
        "10/12/2026 3:57 PM - necromass - 13/3621", "10/12/2026 3:26 PM - Unknown - 13/2921"]
s.timeline.screen.extend((t0 + 0.1, x) for x in rows)
r._death_waiting = [(w[0], w[1], w[2] - 3) for w in r._death_waiting]
sent.clear(); r._death_tick()
check(f"…and answers with the last 3 ({sent})", sent and "grimhound" in sent[0] and "13/2925" in sent[0]
      and "necromass" in "".join(sent) and "Unknown" not in "".join(sent))
# a follower's restart: the loop waits for the leader
c = s.control
c.dir = tempfile.mkdtemp()
from mudpilot.megamud_files import MPath
mp = MPath("Full Glades", "test", "ABCD1234", "ABCD1234", filename=os.path.join(c.dir, "Full Glades.mp"))
s.paths = list(s.paths) + [mp]
res = {"t": time.time(), "connected": True, "walking": True, "loop": True, "title": "Full Glades",
       "path_file": os.path.basename(mp.filename) if mp else "x.mp", "goto": None, "party": [], "follow": "Revolution"}
json.dump(res, open(os.path.join(c.dir, "resume.json"), "w", encoding="utf-8"))
c.load_resume()
if mp:
    check("follower: nothing walks off by itself", not getattr(s, "_drop_resume", None) and s._rejoin.get("then"))
    s._rejoin["t"] = time.time() - 400                  # never got back in
    s.state.view = None
    s._rejoin_tick()
    check(f"…never back with the leader: stays put, Rego carries on ({s.bot.resume and s.bot.resume.get('path')})",
          not getattr(s, "_drop_resume", None) and s.bot.resume and s.bot.resume.get("path") is not None)
else:
    print("(no loop file in this test board — skipping the follower part)")
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
