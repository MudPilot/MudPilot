"""Dan, 2026-10-28:
  - 'You hear movement to the up' in a room with no up exit → 'l u' / 'There are no exits upwards!'. It's a sound
    from beyond a vortex; don't look a direction the room hasn't got.
  - 'pick west' three times on a gate that 'was not locked', then a bash that cost HP. Not locked = just open it."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.look_on_sound = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object()                                 # feed_line only runs while connected
b, g = s.bot, s.state
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

# --- look only toward real exits ---
g.view = RoomView("Darkwood Forest", {"S", "NW"}, [], [], [], time.time()); g.view_seq += 1
sent.clear(); s.safety.feed_line("You hear movement to the up.")
check(f"no up exit: doesn't look up ({sent})", not any("l u" in c or c == "l up" for c in sent))
sent.clear(); s.safety._heard = {}
s.safety.feed_line("You hear movement to the northwest.")
check(f"real exit: looks that way ({sent})", any(c.lower() in ("l nw",) for c in sent))

# --- unlocked gate: open, don't keep picking ---
g.view = RoomView("Dirt Path", {"E"}, [], [], [], time.time(), closed={"W"}) if "closed" in \
    RoomView.__init__.__code__.co_varnames else RoomView("Dirt Path", {"E"}, [], [], [], time.time())
g.view.closed = {"W"}; g.view_seq += 1
b._opening_dir = "W"; b._lock_tries = {"W": 2}
sent.clear(); b.note_line("The gate was not locked.")
check(f"'was not locked' → open, no more picks/bashes ({sent})",
      "open west" in sent and not any("pick" in c or "bash" in c for c in sent) and b._locked_dir is None)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
