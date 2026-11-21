"""0.8.208 (Dan, 2026-11-19): '@stash here' sets the real stash room remotely — the walking loop's, else the default."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
import types
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st); s._no_log_file = True
s.state.candidates = [(14, 6534)]
s.bot._lap_path = None
r = s.remote.c_stash("Miserable", "here")
check(f"not looping: default stash room ({r})", st.stash_room == "14/6534")
st.stash_room = ""
mp = types.SimpleNamespace(title="Stonecaps", filename="stonecaps.mp", steps=[])
s.bot._lap_path = mp
r = s.remote.c_stash("Miserable", "here")
check(f"looping: this loop's stash ({r}, {st.loop_stash})", "14/6534" in (st.loop_stash or {}).values()
      and not st.stash_room and s.bot.x.stash_room() == (14, 6534))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
