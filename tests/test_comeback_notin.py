"""Evolution (Dan, 2026-11-03): back from an update before Buddy, he invited him ("You don't see buddy here."),
went straight back to his loop and, when "Buddy just entered the Realm." came, did nothing — Buddy was left behind.
A remembered member who isn't in yet is waited for like one who dropped, and fetched once they're in."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Evolution"; st.party_comeback = True
st.reinvite_after_reconnect = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g, cb = s.bot, s.state, s.comeback
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g.candidates = [(17, 1623)]
g.party = {"Evolution": {}, "Revolution": {}}
b.x._own_party = True
s._reinvite, s._reinvite_at = ["Buddy"], time.time() - 1
s._reinvite_tick()
check(f"invites him on getting back in ({sent})", "invite Buddy" in sent)
cb.feed_line("You don't see buddy here.")
check(f"not in yet: the loop waits for him ({cb.holding()})", cb.holding() == "Buddy")
sent.clear()
cb.feed_line("Buddy just entered the Realm.")
check(f"he's in: asks where he is to go and get him ({sent})", "/Buddy @where" in sent)
# a stray "You don't see X here" (a typo'd look) long after: nothing
cb.missing.clear(); cb.fetch = None
s._reinvited = {"buddy": ("Buddy", time.time() - 60)}
cb.feed_line("You don't see buddy here.")
check("an old invite: not waited for", not cb.holding())
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
