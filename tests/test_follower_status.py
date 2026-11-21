"""Dan, 2026-11-16: Revolution PVE, back in Evolution's party after a restart, still said "Stopped (before the restart) —
Rego carries on to 13/3010" an hour later; the health watch took it for a stuck character. Following someone: say so."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st); s._no_log_file = True
b = s.bot
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
b.resume = {"path": None, "loop": False, "after": None, "target": (13, 3010)}
b.stop_note = "before the restart"
check(f"stopped, nobody followed: says so ({b.idle_text()})", b.idle_text().startswith("Stopped (before the restart)"))
b.x.note_line("You are now following Evolution.")
check(f"back in Evolution's party ({b.idle_text()})", b.idle_text() == "Following Evolution")
b.x.note_line("You are no longer in a party.")
check(f"party gone: the stop shows again ({b.idle_text()})", b.idle_text().startswith("Stopped"))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
