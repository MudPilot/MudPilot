"""Dan, 2026-11-17: Buddy's Combat button was off after a reconnect; he followed the party three hours without
attacking and @status said just 'idle'."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.send = lambda c, from_bot=False: None
r = s.remote
st.auto_combat = True
assert "Combat OFF" not in r._activity(), r._activity()
st.auto_combat = False
assert "Combat OFF" not in r._activity(), r._activity()
s.bot.x._following = "Evolution"
a = r._activity()
assert a.startswith("Combat OFF"), a
# nothing going on (no walk, nobody to follow, no monsters): plain idle as before
s.bot.x._following = None
s.bot.walking = False
assert "Combat OFF" not in r._activity()
print("OK", a)
