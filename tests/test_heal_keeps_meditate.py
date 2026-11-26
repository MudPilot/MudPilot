"""0.8.227.6 (Dan, 2026-11-25: "revolution seems to be resting instead of meditating"). Meditating for mana at 89% HP
(rest below 80, until 90) and 43% mana, his heal on Miserable stood him up; the 0.8.225 'own heal mid-rest: keep
resting' rule kept him down — but also turned the meditate into a rest. It stays a meditate now; an HP rest
interrupted by a heal is still a rest."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
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
b.send = lambda c, *a, **k: sent.append(c)
st.auto_rest, st.use_meditate, st.meditate_cmd, st.rest_cmd = True, True, "medi", "rest"
st.rest_below_hp, st.rest_until_hp, st.rest_below_ma, st.rest_until_ma = 80, 90, 50, 70
st.smart_rest = False; st.auto_regen_gear = False
g.max_hp, g.hp, g.max_ma, g.ma = 957, 854, 483, 208
g.resting = False; g.in_combat = False
b._rest_begun = True; b._last_spell_at = time.time() - 1; b._cool.clear()
check("healed a teammate mid-meditate: still sitting", b.should_rest([], False))
check(f"…back to meditating, not resting ({sent})", "medi" in sent and "rest" not in sent)
# an HP rest (81%, under 'rest until') stood up by our own heal: still a rest
sent.clear(); g.hp, g.ma = 775, 400
b._rest_begun = True; b._last_spell_at = time.time() - 1; b._cool.clear()
check("HP rest stood up by our heal: still sitting", b.should_rest([], False))
check(f"…and it's a rest ({sent})", "rest" in sent and "medi" not in sent)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
