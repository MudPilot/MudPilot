"""Whose damage is it? Real Paradigm lines (Dan's log, Oct 26): dragonfire / fire elemental lines don't
name the caster — the gesture line before them does. Monster variants tune together."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.spelltune import family

st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st); s._no_log_file = True
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): pass
s.telnet = Tel(); s._entered = True
s.state.party = {"Miserable": {}, "Revolution": {}}
s.bot._cast_target = "drooling geist"; s.bot._last_spell = 5
t = s.spelltune
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
lines = """The drooling geist swipes at Revolution with its claws!
The drooling geist hits Revolution, but the swing glances off!
You make a complex circling gesture!
A withering blast of dragonfire sears drooling geist for 343 damage!
Revolution makes a sweeping gesture!
A fire elemental appears and scorches drooling geist for 182 damage, then vanishes!
A spear of dark energy impales Revolution for 22 damage!
The tall nightshade claws Revolution for 4 damage!
The drooling geist claws you for 9 damage!""".splitlines()
for l in lines:
    s._line([(l, Style())])
f = t._fight
check(f"dragonfire is mine, fire elemental is Revolution's, monster hits ignored ({f and f['dmg']})",
      f and f["dmg"] == {"miserable": 343, "revolution": 182})
s.bot._cast_target = "tall nightshade"
s._line([("Your flaming magma blast strikes tall nightshade for 122 damage!", Style())])
check("magma blast is mine", t._fight["dmg"] == {"miserable": 122})
check("variants tune together", family("large drooling geist") == family("nasty drooling geist") == "drooling geist"
      and family("tall nightshade") == family("short nightshade") == "nightshade" and family("drooling geist") == "drooling geist")
s.bot._last_hit_at = 0
s.bot._cast_target = "drooling geist"
s._line([("You make a complex circling gesture!", Style())])
s._line([("A withering blast of dragonfire sears drooling geist for 300 damage!", Style())])
check("our spell landing is noticed even when the line doesn't say 'Your'", time.time() - s.bot._last_hit_at < 2)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
