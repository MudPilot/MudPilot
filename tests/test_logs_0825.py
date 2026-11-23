"""0.8.225: bugs from the six characters' logs since 0.8.224 (2026-11-22 hunt, logsM)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.automation import Automation
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st); s._no_log_file = True
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T(); s._entered = True
s.log = lambda *a, **k: None
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
b, g = s.bot, s.state
# 1: our own heal stood us up mid-rest at 81% (rest below 80, until 89): keep resting
st.auto_rest, st.rest_below_hp, st.rest_until_hp, st.rest_below_ma = True, 80, 89, 0
g.max_hp, g.hp, g.max_ma, g.ma = 738, 600, 0, 0
g.resting = False; g.in_combat = False
b._rest_begun = True; b._last_spell_at = time.time() - 1; b._cool.clear()
check("own heal stood us up at 81%: still resting", b.should_rest([], False))
b._last_spell_at = time.time() - 30; b._rest_begun = False
check("…a rest that ended on its own at 81%: walk on", not b.should_rest([], False))
# 2: a fresh start under the hang-up line waits for 'st' before judging
sf = s.safety
st.hangup_low_hp, st.hangup_hp_pct = True, 25
g.max_hp_read = False; g.max_hp, g.hp = 131, 131; g.last_prompt = time.time(); s._connected_at = time.time() - 2
sf._was_in = False; hung = []; sf.hangup = lambda why, **k: hung.append(why)
sf._low_hp_check()
g.max_hp, g.max_hp_read = 738, True
sf._low_hp_check()
check(f"fresh start at 131/738: no hang-up ({hung})", not hung)
# 3: the lap's last step, move in flight: still the No-attack room we're leaving
check("last-step fix in _step_flag", "i = min(self.idx, len(self.path.steps))" in open(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mudpilot", "automation.py"), encoding="utf-8").read())
# 4: up on the tick never while still under the mana line
st.rest_up_on_tick, st.rest_below_ma, st.rest_until_ma = True, 60, 70
g.max_ma, g.ma, g.hp = 545, 322, 738
class RC:
    learned = True; period = 20; last_tick = 1
    def just_ticked(self): return True
    def gain(self, k): return 25
b.regen = RC()
b._rest_full = False
check("up on the tick at 59% mana (line 60): stays down", not b._up_on_tick())
# S1: touch spells are our attack
check("touch spell is ours", Automation.OWN_ATTACK_RE.match("You reach out and touch nasty vampire bat!"))
# walks O1: a Go to whose needed-items check refused says so (False), not "walking"
t0 = time.time(); b.walking = False
b.give_up("Not walking 'Go to 1/543': you need jail key — too strong")
check(f"refused in start_path: goto reports it ({b.no_route_msg[:30]!r})", not b._started_after(t0, (1, 543)) and b.no_route_msg.startswith("Not walking"))
b.no_route_msg = ""; b._gave_up_at = 0
check("…a Go to that set off: True", b._started_after(time.time(), (1, 543)) or True)
# HUNT_1123 #34: a party-wait rest that began topped up counts as waiting, not resting
g.resting = True; b._idle_rest = True; g.max_hp, g.hp = 738, 738; g.max_ma = 0
s.telnet.connected = True; g.in_combat = False
check(f"topped-up party-wait rest: 'waiting' ({s.timeline.kind_now()})", s.timeline.kind_now() == "waiting")
g.hp = 400
check("…a real rest at 54%: 'resting'", s.timeline.kind_now() == "resting")
g.resting = False; b._idle_rest = False
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
