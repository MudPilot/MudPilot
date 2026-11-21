"""Dan, 2026-11-16: he walked Miserable to the stash room to collect the cash and use the coin bag on it (3 uses a day);
MudPilot hid the cash again right before he used it. The stash room only stashes while looping / walking, and standing
there by hand holds it for 3 minutes after."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.gamestate import RoomView
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st); s._no_log_file = True
b, g, x = s.bot, s.state, s.bot.x
sent = []
b.send = sent.append; x.send = sent.append
st.stash_room, st.stash_coins, st.stash_min_copper = "14/6534", ["gold crown"], 0
g.candidates = [(14, 6534)]
g.view = RoomView("Bristlewood Grove", {"E"})
g.in_combat = False
g.coins = {"gold crown": 500}
g.carrying = "500 gold crowns, woodland robes (Worn)"
b.walking = False
check(f"standing there by hand: nothing hidden ({sent})", not x.stash_tick() and not sent)
b.walking = True; b._cool.pop("stash", None)
check(f"Rego straight away: still held ({sent})", not x.stash_tick() and not sent)
x._stash_manual_at = time.time() - 200; b._cool.pop("stash", None)
check(f"3 minutes later, looping: hides it ({sent})", x.stash_tick() and any("gold crown" in c for c in sent))
# Dan, 2026-11-18: once a visit — picking the gold back up by hand (coin bag) doesn't get it hidden again
sent.clear(); b._cool.pop("stash", None)
check(f"same visit, gold picked back up: not hidden again ({sent})", not x.stash_tick() and not sent)
real_c = g.candidates
g.candidates = [(1, 1)]; x.stash_tick(); g.candidates = real_c            # walked out and back in
b._cool.pop("stash", None)
s._user_sent_at = time.time()
check(f"back in, but you typed just now: held ({sent})", not x.stash_tick() and not sent)
s._user_sent_at = 0; b._cool.pop("stash", None)
check(f"next visit, hands off: hides it ({sent})", x.stash_tick() and any("gold crown" in c for c in sent))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
