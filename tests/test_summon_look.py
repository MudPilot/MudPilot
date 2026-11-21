"""Dan, 2026-10-28 at the Black Steel Gate: 'touch statue' — "The statue animates, and attacks!" — and MudPilot sent
i, abil and par and would have stood there while the statue hit Buddy. A summon command is followed by a look, and
a line like that makes it look too."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None
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
check("touch statue / touch hammer are summon commands", {"touch statue", "touch hammer"} <= s.world.summon_triggers)
s.send("touch statue", from_bot=True)
check(f"…followed straight away by a look ({sent})", sent[-2:] == ["touch statue", ""])
sent.clear()
s.send("say hello")
check(f"other commands aren't ({sent})", sent == ["say hello"])
s.state.need_refresh = False
s.state.feed_line([("The statue animates, and attacks!", None)])
check("'animates, and attacks!' → look", s.state.need_refresh)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
