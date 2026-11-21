"""Dan, 2026-11-18: Revolution (druid) had a 'flux' rule and sent it again and again — 'Your command had no effect.'"""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st); s._no_log_file = True
b = s.bot
logs = []
b.log = lambda m, *a, **k: logs.append(m)
for i in range(3):
    b._buff_cast["flux"] = time.time()
    b.note_line("Your command had no effect.")
assert b._buff_noeffect["flux"][0] == 3, b._buff_noeffect
assert any("skipping it for 10 min" in m for m in logs), logs
# a single one (knockdown) long ago doesn't add up
b._buff_noeffect["ntap"] = (1, time.time() - 300)
b._buff_cast["ntap"] = time.time() + 1
b.note_line("Your command had no effect.")
assert b._buff_noeffect["ntap"][0] == 1
print("OK")
