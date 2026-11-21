"""Buddy, 2026-10-30: a bless 'use longsword' (made while it was in hand) with the longbow out — "You do not have
shimmering longsword equipped." Swap it in, use it, swap the longbow back."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.telnet.sock = object(); sent = []; s.telnet.send_line = lambda c: sent.append(c)
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


BOW = ("visored greathelm (Head), full plate corselet (Torso), silvery longbow (Weapon Hand), log raft, "
       "shimmering longsword, scroll of entangle")
s.state.carrying = BOW
s.send("use longsword", from_bot=True)
check(f"longbow out: swap in, use, swap back ({sent})",
      sent == ["eq shimmering longsword", "use shimmering longsword", "eq silvery longbow"])
sent.clear()
s.state.carrying = BOW.replace("silvery longbow (Weapon Hand)", "silvery longbow").replace(
    "shimmering longsword,", "shimmering longsword (Weapon Hand),")
s.send("use longsword", from_bot=True)
check(f"longsword in hand: just use it ({sent})", sent == ["use longsword"])
sent.clear()
s.state.carrying = BOW
s.send("use longsword")
check(f"typed by you: sent as typed ({sent})", sent == ["use longsword"])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
