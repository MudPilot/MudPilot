"""Dan, 2026-10-30, the Ancient Ruin: Revolution and Buddy each waited for the other to invite them — '@invite' both ways
every 15 s, invites to Buddy rooms away, 18 disband/joins in a second — and after Buddy's @summon and Dan's Stop,
Revolution set off for Buddy again the same second. Invite once and only in the same room; Stop ends the chase."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object(); s._connected_at = time.time() - 60
sent = []
s.telnet.send_line = lambda c: sent.append(c)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


g, b, cb = s.state, s.bot, s.comeback
g.candidates = [(3, 559)]
g.view = RoomView("Ancient Ruin, Inside Arch", {"N"}, [], [], [], time.time())
out = s.remote.c_invite("Buddy", "")
check(f"@invite from someone rooms away: no invite ({out}, {sent})", not any(c.startswith("invite") for c in sent))
s._rejoin = {"leader": "Buddy", "t": time.time(), "asked": time.time(), "tries": 0, "joined": False}
g.view = RoomView("Ancient Ruin, Inside Arch", {"N"}, [], [], ["Buddy"], time.time())
sent.clear(); s.remote.c_invite("Buddy", "")
check(f"…here: invited, and no more waiting for Buddy to invite me ({sent})",
      "invite Buddy" in sent and not getattr(s, "_rejoin", None))

# invite if seen: once as they show up, not every minute while they stand there
p = s.players._seen("Evolution"); p["invite_if_seen"] = True
g.view = RoomView("Ancient Ruin, Inside Arch", {"N"}, [], [], ["Evolution"], time.time())
sent.clear(); s.players.on_room(g)
first = [c for c in sent if c.startswith("invite")]
p["_invited"] = time.time() - 120
sent.clear(); s.players.on_room(g)
check(f"invite if seen: once while they stay ({first}, then {sent})",
      first == ["invite Evolution"] and not any(c.startswith("invite") for c in sent))

# disband your own party first: once, not a burst
for _ in range(5):
    s._join_sent = ("Buddy", time.time())
    s._disband_then_join("You must disband your own party first!")
check(f"disband → join once, not five times ({sent.count('disband')})", sent.count("disband") <= 1)

# Stop ends the chase
cb.fetch = {"name": "Buddy", "phase": "going", "room": (3, 559), "t": time.time()}
cb.missing = {"Buddy": {"t": time.time(), "why": "left behind"}}
s._rejoin = {"leader": "Buddy", "t": time.time(), "asked": time.time(), "tries": 0, "joined": False}
b.stop("Stopped by you")
check("Stop: no comeback, no rejoin", cb.fetch is None and not cb.missing and not s._rejoin)
st.party_comeback = True
b.x.leading = lambda: True
g.party = {"Revolution": {}, "Buddy": {}}
cb.feed_line("Buddy is no longer following you.")
check("…and Buddy wandering off right after isn't chased", cb.fetch is None and "Buddy" not in cb.missing)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
