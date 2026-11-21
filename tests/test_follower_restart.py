"""Dan, 2026-10-28: Buddy follows Revolution and Evolution (MegaMUD) — on an update they walked off and left him. A
follower that restarts @stops its leader first; back in, it asks '@invite', joins, then '@rego'."""
import os, sys, time, json, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, control
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
d = tempfile.mkdtemp()
c = control.ControlBox(s, folder=d)
control.by_launcher = lambda: True
s.bot.x.note_line("You are now following Revolution.")
check("following Revolution", s.bot.x._following == "Revolution")
open(os.path.join(d, "restart.request"), "w").close()
closed = []
c.on_restart = lambda: closed.append(1)
c.started = time.time() - 60
c._next_check = 0
c.tick()
check("…and doesn't close in the same moment", not closed)
c._next_check = 0
c.tick()
check("closes on the next check", closed)
check(f"restart asked → '/Revolution @stop' first ({sent})", "/Revolution @stop" in sent)
r = json.load(open(os.path.join(d, "resume.json"), encoding="utf-8"))
check(f"resume.json remembers whom we follow ({r.get('follow')})", r.get("follow") == "Revolution")
# --- the new MudPilot after the restart
s2 = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s2._no_log_file = True
sent.clear()
s2.telnet = T(); s2._entered = True; s2._connected_at = time.time() - 10
c2 = control.ControlBox(s2, folder=d)
c2.load_resume()
check("will ask for an invite", getattr(s2, "_rejoin", None) and s2._rejoin["leader"] == "Revolution")
from mudpilot.gamestate import RoomView
s2.state.view = RoomView("Dark Corridor", {"S"}, [], [], ["Revolution"], time.time())   # back where he stopped
s2._rejoin_tick()
check(f"he's in the room: '/Revolution @invite' ({sent})", "/Revolution @invite" in sent)
sent.clear()
s2.players.feed_line("Revolution has invited you to join their party.") if hasattr(s2.players, "feed_line") else \
    s2.players.note_line("Revolution has invited you to join their party.")
check(f"invited → joins ({sent})", "join Revolution" in sent)
s2.bot.x.note_line("You are now following Revolution.")
sent.clear()
s2._rejoin_tick()
check(f"in the party → '/Revolution @rego' ({sent})", "/Revolution @rego" in sent and s2._rejoin is None)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
