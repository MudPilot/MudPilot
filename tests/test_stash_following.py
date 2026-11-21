"""0.8.208 (Dan, 2026-11-19): Miserable following Revolution round Stonecaps never stashed — his Stonecaps stash
(14/6534) belonged to 'the loop I'm walking', and a follower walks none. Following through one of his loops' stash
rooms stashes too (still once a visit, never right after you typed)."""
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
st.stash_room = ""; st.loop_stash = {"stonecaps.mp": "14/6534"}; st.stash_coins = ["gold crown"]; st.stash_min_copper = 0
g.view = RoomView("Bristlewood Grove", {"E"}); g.in_combat = False
g.coins = {"gold crown": 500}; g.carrying = "500 gold crowns"
b._lap_path = None
x.leader = lambda: "Revolution"
g.candidates = [(14, 6534)]
check(f"following through his Stonecaps stash room: hides the gold ({sent})",
      x.stash_tick() and any("gold crown" in c for c in sent))
sent.clear(); b._cool.pop("stash", None); x._stashed_visit = False
g.candidates = [(14, 6535)]
check(f"another room: nothing ({sent})", not x.stash_tick() and not sent)
x.leader = lambda: None; g.candidates = [(14, 6534)]; b.walking = False; b._cool.pop("stash", None)
check(f"not following, no loop: nothing (by hand) ({sent})", not x.stash_tick() and not sent)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
