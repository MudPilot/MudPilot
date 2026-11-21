"""Buddy, 2026-10-28: logged back in to a dark room — pressed Enter every 6 s for minutes ("The room is very dark")
and answered Miserable's '@summon 8 437' with "not sure where I am yet". In the dark: ask 'pro'; a summon that comes
before we know the room waits for it, then goes."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"; st.locate_cmd = "pro"
st.remote_allow = ["Miserable"] if hasattr(st, "remote_allow") else None
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
b, g = s.bot, s.state
g.candidates = []
g.feed_line([("The room is very dark - you can't see anything", None)])
check("dark seen", time.time() - g.dark_at < 2)
b._unsure_since = time.time() - 5
b._locate_at = 0
check(f"unknown room in the dark → asks 'pro' ({b.maybe_locate()}, {sent})", "pro" in sent)
sent.clear()
msg = s.remote.c_summon("Miserable", "8 437")
check(f"summon before we know the room: waits, says so ({msg})", "on my way in a moment" in msg)
g.candidates = [(8, 435)]
s.remote._summon_tick()
check(f"…room known → goes ({b.walking}, {[c for c in sent if 'Miserable' in c]})",
      b._goto_target == (8, 437) or b.walking or any("on my way" in c or "no route" in c for c in sent))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
