"""Dan, 2026-11-18: 'it clearly says rest below 70% mana' — Revolution walked on at 44% because the mana throttle let
him go down to half the line on cheap spells. The line is the line now."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
st.rest_below_ma, st.rest_until_ma, st.mana_throttle, st.use_meditate = 70, 90, True, True
st.rest_below_hp, st.rest_until_hp = 80, 90
s = Session(st); s._no_log_file = True
s.send = lambda c, from_bot=False: None
b, gs = s.bot, s.state
b.send = lambda c, *a, **k: None
gs.max_hp, gs.hp, gs.max_ma, gs.ma = 932, 900, 458, 200      # 44% mana, HP fine
gs.resting = False
b.mana_rest_can_wait = lambda: True                           # plenty of cheap casts left
assert b.should_rest([], False), b.status
print("OK", b.status)
