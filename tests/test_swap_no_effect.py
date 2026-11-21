"""Dan, 2026-11-05: Miserable PVE "been not looping last 2 times i've checked today". Its post-meditate swap
('eq shawl^Meq pho^Mremove white gold^Meq platinum ring^Mst') gets 'Your command had no effect.' for a line that
does nothing, just as the walk sets off again — that was read as the path's room command failing: a resync, a
drift, and 7 in 5 min stopped the loop. A swap's own reply isn't the path's."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st); s._no_log_file = True
b = s.bot
b.send = lambda c, **k: None
b.log = lambda m, *a, **k: None
located = []
b.locate_now = lambda why="": located.append(why) or True
from mudpilot.megamud_files import MPath
b.walking, b.path = True, MPath(name="Tidepool (Longer)", author="", start_hash="a", end_hash="b")
b._step_sent_at = time.time()
b.send_macro("eq shawl^Meq pho^Mst")
b.note_line("Your command had no effect.")
check(f"right after the swap line: not a path problem ({located})", not located)
b._macro_at = time.time() - 10
b._step_sent_at = time.time()
b.note_line("Your command had no effect.")
check(f"the path's own command doing nothing still checks where we are ({located})", located)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
