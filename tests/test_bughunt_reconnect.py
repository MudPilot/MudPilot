"""0.8.201 bug hunt (reconnect / PvP / remote): regression checks for bug_hunt/reconnect_pvp.md #1-5,
remote_security.md F2-F7 and stock_routing #7 (first run asks the board)."""
import json, os, queue, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.ansi import Line, Style
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


class T:
    def __init__(self):
        self.connected = True
        self.events = queue.Queue()
        self.sent = []
    def send_line(self, x): self.sent.append(x)
    def close(self):
        self.connected = False
        self.events.put(("closed", "hung up"))     # the reader thread posts this later, like the real one


def make(name="Miserable"):
    st = config.Settings(); st.save = lambda: None; st.my_name = name
    s = Session(st); s._no_log_file = True
    s.telnet = T(); s._entered = True
    s.notify.send = lambda *a, **k: None
    return s, st


# --- reconnect #1: relog-instead-of-hang comes back in 5 s, not a whole reconnect_delay
s, st = make()
st.relog_instead_of_hang, st.reconnect_delay, st.auto_reconnect = True, 60, True
st.hangup_low_hp = False
s.safety.hangup("PvP: Zed attacked")
kept = s._closed_at
s._on_closed("hung up")                       # the reader's "closed" arrives after the hang-up
check(f"relog: _closed_at kept ({time.time() - s._closed_at:.0f} s ago, want ~55)", s._closed_at == kept
      and time.time() - s._closed_at > 50)
s2, st2 = make()
s2._on_closed("connection closed by host")
check("an ordinary drop still notes now", abs(s2._closed_at - time.time()) < 2)

# --- reconnect #2: a hang-up survives a restart (resume.json), older files still load
s, st = make()
d = tempfile.mkdtemp()
s.control._p = lambda name: os.path.join(d, name)
s.telnet.connected = False
s.hold_realm = True
s.safety.hung_up_until = time.time() + 600
s.control.write_resume()
r = json.load(open(os.path.join(d, "resume.json"), encoding="utf-8"))
check(f"resume.json has the hang-up ({r.get('hung_up_until'):.0f}, hold {r.get('hold_realm')})",
      r.get("hung_up_until", 0) > time.time() + 500 and r.get("hold_realm") is True)
s3, st3 = make()
s3.control._p = lambda name: os.path.join(d, name)
back = s3.control.load_resume()
check(f"restored: held at the menu, hung up, hold_off {back.get('hold_off', 0):.0f} s",
      s3.hold_realm and not s3.safety.may_reconnect() and 500 < back.get("hold_off", 0) <= 600)
s.safety.hung_up_until = float("inf")
s.control.write_resume()
s4, _ = make()
s4.control._p = lambda name: os.path.join(d, name)
back = s4.control.load_resume()
check("stay off until you connect: -1", back.get("hold_off") == -1 and s4.safety.hung_up_until == float("inf"))
json.dump({"t": time.time(), "connected": True, "walking": False}, open(os.path.join(d, "resume.json"), "w"))
s5, _ = make()
s5.control._p = lambda name: os.path.join(d, name)
back = s5.control.load_resume()
check("an older resume.json: no hold, connects as before", back and back.get("connect") and "hold_off" not in back
      and not getattr(s5, "hold_realm", False) and s5.safety.may_reconnect())

# --- reconnect #3: a restart while the line is down keeps the loop and comes back in
s, st = make()
s.control._p = lambda name: os.path.join(d, name)
st.auto_reconnect = True
s.telnet.connected = False
s._want_connected = True
class MP:
    title, filename, is_loop = "Full Glades", "Full_Glades.mp", True
s._drop_resume = {"path": MP(), "loop": True, "after": None, "target": None}
s.control.write_resume()
r = json.load(open(os.path.join(d, "resume.json"), encoding="utf-8"))
check(f"line down: walking {r['walking']}, connected {r['connected']}, {r['path_file']}",
      r["walking"] and r["connected"] and r["path_file"] == "Full_Glades.mp" and r["hung_up_until"] == 0)
os.remove(os.path.join(d, "resume.json"))
s._want_connected = False
s._drop_resume = None
s.control.write_resume()
r = json.load(open(os.path.join(d, "resume.json"), encoding="utf-8"))
check("disconnected by you: not connected, not walking", not r["connected"] and not r["walking"])
os.remove(os.path.join(d, "resume.json"))

# --- reconnect #4: a second MudPilot on a folder in use refuses (not only via the launcher)
from mudpilot import app as mpapp
dd = tempfile.mkdtemp()
os.environ.pop("MUDPILOT_LAUNCHER", None)
os.makedirs(os.path.join(dd, "control"))
json.dump({"pid": os.getppid(), "t": time.time()}, open(os.path.join(dd, "control", "in-use.json"), "w"))
check("folder in use by a live MudPilot: refused", mpapp.claim_data_folder(dd) is False)
os.remove(os.path.join(dd, "control", "in-use.json"))
check("free folder: claimed", mpapp.claim_data_folder(dd) and
      json.load(open(os.path.join(dd, "control", "in-use.json"))).get("pid") == os.getpid())
os.environ["MUDPILOT_LAUNCHER"] = "1"
json.dump({"pid": os.getppid(), "t": time.time()}, open(os.path.join(dd, "control", "in-use.json"), "w"))
check("opened by the launcher: it holds the folder already", mpapp.claim_data_folder(dd) is True)
os.environ.pop("MUDPILOT_LAUNCHER", None)

# --- reconnect #5: back in after a drop, the walk waits for HP and the re-invited party
s, st = make()
st.rest_below_hp, st.auto_rest, st.comeback_wait_mins, st.reinvite_after_reconnect = 60, True, 5, True
s.state.max_hp, s.state.hp = 100, 30
s._reinvited = {"buddy": ("Buddy", time.time())}
s._comeback_hold()
check(f"low HP: walk held ({list(getattr(s.bot, 'holds', {}))})", "reconnect" in getattr(s.bot, "holds", {}))
check(f"re-invited Buddy: regroup waits ({(s._regroup or {}).get('names')})", (s._regroup or {}).get("names") == ["Buddy"])
s._resume_tick()
check("still low: still held", "reconnect" in s.bot.holds)
s.state.hp = 90
s._resume_tick()
check("HP back over the rest line: released", "reconnect" not in s.bot.holds)
s, st = make()
s.state.max_hp, s.state.hp = 100, 95
s._comeback_hold()
check("HP fine, nobody re-invited: no hold", not getattr(s.bot, "holds", {}) and not getattr(s, "_regroup", None))

# --- remote: party commands from our leader (or a 'party' tick); members keep the everyday ones
s, st = make("Buddy")
st.remote_enabled = True
st.remote_channels = {"telepath": True}
s.state.party = {"Miserable": {}, "Buddy": {}, "Revolution": {}}
st.party_leader = "Miserable"
rm = s.remote
check("leader may @stash", rm.allowed("Miserable", "party", "@stash"))
check("a member may not @stash / @panic", not rm.allowed("Revolution", "party", "@stash")
      and not rm.allowed("Revolution", "party", "@panic"))
check("a member may @wait / @ok / @comeback / @mpsync / @held", all(rm.allowed("Revolution", "party", c)
      for c in ("@wait", "@ok", "@comeback", "@mpsync", "@held")))
st.remote_players = {"Zed": ["query"]}
check("a stranger ticked for queries gets no party command", not rm.allowed("Zed", "party", "@comeback"))
st.remote_players = {"Zed": ["party"]}
check("the 'party' tick still gives them", rm.allowed("Zed", "party", "@stash"))

# --- remote F4: refusals are rate-limited per sender
s, st = make()
st.remote_enabled, st.remote_channels, st.remote_warn_denied = True, {"telepath": True}, True
st.remote_players = {}
for _ in range(10):
    s.remote.handle("telepath", "Zed", "@where")
s.remote.reply = getattr(s.remote, "reply")
out = [x for x in s.telnet.sent if x.lower().startswith("/zed")]
q = getattr(s.remote, "_paced", [])
check(f"10 refused lines → one refusal ({len(out)} sent, {len(q)} queued)", len(out) + len(q) <= 1)

# --- remote F5: a stranger's '{mpsync ok}' isn't a peer
s, st = make()
s.state.party = {"Miserable": {}, "Buddy": {}}
saves = []
st.save = lambda: saves.append(1)
check("stranger's mpsync ok: not taken", not s.partysync.answer("Zed", "{mpsync ok 0.8.201 tune lvl=1}")
      and "Zed" not in s.partysync.peers and not saves)
check("a member's mpsync ok: taken", s.partysync.answer("Buddy", "{mpsync ok 0.8.201 tune lvl=47}")
      and "Buddy" in s.partysync.peers)

# --- remote F6: unicode digits don't crash int()
s, st = make()
try:
    s.training.party_msg("Buddy", "st l=²")
    good = True
except ValueError:
    good = False
check("'@ptrain st l=²' doesn't raise", good)
check("'@flags ²' answers without an error", "error" not in str(s.remote.c_flags("Buddy", "²")).lower())

# --- remote F7: a long chat line without ESC[K still marks its wrapped half
s, st = make()
g = s.state
def L(text, fresh=False):
    ln = Line([(text, Style())]); ln.fresh = fresh; return ln
g.feed_line(L("Zed gossips: " + "x" * 66))
g.feed_line(L("Evolution telepaths: @do drop all"))
check("wrapped half of an un-tidied long chat line is a continuation", g.continuation)
g.feed_line(L("The kobold hits you for 5 damage!"))
check("no ESC[K: the line after the short last piece is game text again (not swallowed)", not g.continuation)
g.feed_line(L("Zed gossips: hi"))
g.feed_line(L("Evolution telepaths: @where"))
check("after a short chat line the next line is read normally", not g.continuation)
g.feed_line(L("Zed gossips: hi", fresh=True))
g.feed_line(L("x" * 20))
check("Paradigm (ESC[K): a wrapped piece is still a continuation as before", g.continuation)

# --- stock_routing #7: a fresh install asks the board; an install with a profile doesn't
pd = tempfile.mkdtemp()
old_pd, old_settings, old_state = config.PROFILES_DIR, config.SETTINGS, config.APP_STATE
config.PROFILES_DIR = pd
config.SETTINGS = os.path.join(pd, "nope-settings.json")
config.APP_STATE = os.path.join(pd, "nope-app.json")
try:
    check("no profiles: first run", config.Settings.load("Default")._first_run is True)
    open(os.path.join(pd, "Miserable.json"), "w").write("{}")
    check("a profile exists: not a first run", config.Settings.load("Miserable")._first_run is False)
finally:
    config.PROFILES_DIR, config.SETTINGS, config.APP_STATE = old_pd, old_settings, old_state
check("Settings() made in code isn't a first run", config.Settings()._first_run is False)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
