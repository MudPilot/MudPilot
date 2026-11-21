"""Dan, 2026-11-04: "auto-join when invited should be automatic if the player already has @ commands also. No need
to wait for an @invite." The game's line: 'Buddy has invited you to follow him.'"""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, **k: sent.append(c)
s.log = lambda m, *a, **k: None
st.remote_players = {"Buddy": ["query", "move"], "Stranger": []}
s.bot.note_line("Buddy has invited you to follow him.")
check(f"invited by someone with @ commands: joins ({sent})", "join Buddy" in sent)
sent.clear()
s.remote.c_join("Buddy", "")
check(f"…and their @join right after doesn't join twice ({sent})", "join Buddy" not in sent)
sent.clear()
s.bot.note_line("Stranger has invited you to follow her.")
s.bot.note_line("Roadkill has invited you to follow him.")
check(f"no @ commands here: waits, as before ({sent})", not any(c.startswith("join") for c in sent))
st.disallow_remote = True
s.bot.note_line("Buddy has invited you to follow him.")
check("remote control off: doesn't", not any(c.startswith("join") for c in sent))
st.disallow_remote = False
s.remote._joined = {}
s.remote.c_join("Evolution", "")
check(f"a plain @join still joins ({sent})", "join Evolution" in sent)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
