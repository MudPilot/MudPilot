"""0.8.50: the server tick (enter on tick, timed commands), stop on danger, info-command rules, any-key
macros, auto-track."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.macros import key_name
from mudpilot.tick import parse_cmds

here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = Tel(); s._entered = True
b, w, g = s.bot, s.world, s.state
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)

# --- timed commands
check("'0.3 resting look' read", parse_cmds(["0.3 resting look", "x y", "9 any z"]) == [(0.3, "resting", "look")])
tk_ = s.servertick
tk_.note(time.time() - 0.5)          # a tick went off half a second ago
st.tick_cmds = ["0.3 resting look"]
g.resting = True; g.in_combat = False
sent.clear(); tk_.tick()
check("sent 0.3 s into the tick while resting", sent == ["look"])
sent.clear(); tk_.tick()
check("…once per tick", sent == [])
tk_._sent["0.3 resting look"] -= 5      # a tick later (the anchor moved with it)
tk_.note(time.time() - 0.5)
sent.clear(); tk_.tick()
check("…and again next tick", sent == ["look"])
g.resting = False
tk_._sent.clear(); sent.clear(); tk_.tick()
check("not while not resting", sent == [])

# --- regen tick learned from the prompt
tk_.anchor = 0; tk_._hp = None
g.hp, g.ma = 500, 400; g.in_combat = False
tk_.on_prompt()
g.hp = 520; b._last_spell_at = 0
tk_.on_prompt()
check("HP going up by itself = a tick", time.time() - tk_.anchor < 1)

# --- enter on tick
st.enter_on_tick = True
tk_.note(time.time() - 1.0)
d = tk_.enter_delay()
check("enter waits for just after the next tick", d is not None and 3.5 < d < 4.6)
st.enter_on_tick = False
check("…off = straight in", tk_.enter_delay() is None)

# --- stop on danger
st.relog_instead_of_hang = True; st.stop_on_danger = True
s.hold_realm = False
s.safety.hangup("HP 50/684 below 30%")
check("low-HP hang-up with relog on: held at the menu", s.hold_realm)
s.telnet.connected = True; st.relog_instead_of_hang = False

# --- info command rules
st.info_cmd_rules = {"par": {"gap": 10, "no_combat": True, "no_walking": False}}
b.info_stats = {}; b._info_q = {}
sent.clear()
g.in_combat = False
b.send("par")
check("par goes out", sent == ["par"])
sent.clear(); b.send("par")
check("…not again within 10 s (held)", sent == [] and "par" in b._info_q)
b.info_stats["par"]["last"] = time.time() - 20
g.in_combat = True
b._info_flush()
check("…still held in combat", sent == [])
g.in_combat = False
b._info_flush()
check("…and goes out once allowed", sent == ["par"])
st.info_cmd_rules = {}

# --- any-key macros
check("Ctrl+Q is a macro key", key_name("q", 0, 4, True) == "Ctrl+Q")
check("Ctrl+C stays copy", key_name("c", 0, 4, True) is None)
check("Home is a macro key", key_name("Home", 36, 0, True, True) == "Home")
check("plain letters aren't", key_name("a", 0, 0, True) is None)

# --- auto-track
p = s.players.get("Vexx")
p["auto_track"] = True
started = []
s.tracker.start = lambda n: started.append(n)
s.players.feed_line("Vexx just entered the Realm.")
s.players._track_wanted = ("Vexx", time.time() - 10)
b.walking = False; g.in_combat = False
s.players.tick()
check("a flagged player coming on is tracked when idle", started == ["Vexx"])


# --- damaged map data heals itself
import tempfile, shutil as _sh
d_ = tempfile.mkdtemp()
pth = os.path.join(d_, "world.db")
_sh.copy2(os.path.join(here, "mudpilot", "bundled", "Stock.db"), pth + ".old")
with open(os.path.join(here, "mudpilot", "bundled", "Stock.db"), "rb") as f_:
    raw = f_.read()
with open(pth, "wb") as f_:
    f_.write(raw[:4096] + b"\x00" * 100000 + raw[200000:400000])      # cut short + scribbled, like a crash mid-write
w2 = Session._open_world(pth)
check("a damaged world.db is put aside and the last good copy used", w2.loaded and os.path.exists(pth + ".damaged"))
_sh.rmtree(d_, ignore_errors=True)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
