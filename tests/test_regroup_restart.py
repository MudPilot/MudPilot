"""After a MudPilot restart the leader waits for the party it had, re-inviting them, instead of looping solo
(Dan, 2026-10-28: Miserable PVE ran off before Buddy was back in the realm, had to @summon by hand)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.reinvite_after_reconnect = True
st.comeback_wait_mins = 5
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
now = time.time()
s._regroup = {"names": ["Buddy"], "t": now, "asked": 0, "until": now + 300}
g.party = {"Miserable": {}}                               # Buddy not back yet
g.view = RoomView("Ancient Crypt", {"S"}, [], [], [], now); g.view_seq += 1
holds = b.walk_holds()
check(f"Buddy missing: walk is held ({holds})", "regroup" in holds)
# Buddy logs in at our spot: in the room → invite him
g.view = RoomView("Ancient Crypt", {"S"}, [], [], ["Buddy"], time.time()); g.view_seq += 1
s._regroup["asked"] = 0
b.regroup_hold()
check(f"Buddy in the room: invited ({sent})", "invite Buddy" in sent)
# he joins the party → hold clears, walk runs
g.party = {"Miserable": {}, "Buddy": {}}
check("Buddy joined: no regroup hold", "regroup" not in b.walk_holds() and s._regroup is None)
# nobody comes back before the window closes → carry on solo
sent.clear()
s._regroup = {"names": ["Buddy"], "t": now, "asked": 0, "until": time.time() - 1}
g.party = {"Miserable": {}}
check("window closed: carries on, hold gone", "regroup" not in b.walk_holds() and s._regroup is None)
# the setting off → no holding
s._regroup = {"names": ["Buddy"], "t": time.time(), "asked": 0, "until": time.time() + 300}
st.reinvite_after_reconnect = False
check("reinvite off: no restart hold", b.regroup_hold() is None)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
