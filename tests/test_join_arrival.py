"""0.8.99 party fixes (Dan, 2026-10-28):
  - @join is resent if they don't join (Revolution had no remotes yet, so the one @join did nothing).
  - arrived where someone summoned us but they're not here → verify the room (pro) and @where them."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.party_comeback = True
st.invite_join_cmd = "/{name} @join"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
b, g = s.bot, s.state
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

# --- @join retry ---
t = time.time() - 9
s._join_watch = {"Revolution": {"t": t, "tries": 1}}
g.party = {"Miserable": {}}
sent.clear(); s._join_watch_tick()
check(f"no join after 8s: @join resent ({sent})", sent == ["/Revolution @join"] and s._join_watch["Revolution"]["tries"] == 2)
s._join_watch["Revolution"]["t"] = time.time()
sent.clear(); s._join_watch_tick()
check("…not again within 8s", not sent)
g.party = {"Miserable": {}, "Revolution": {}}
s._join_watch_tick()
check("joined → watch cleared", "Revolution" not in s._join_watch)
# gives up after 5
s._join_watch = {"Revolution": {"t": time.time() - 9, "tries": 5}}
g.party = {"Miserable": {}}
sent.clear(); s._join_watch_tick()
check(f"5 tries → gives up, no more ({sent})", not sent and "Revolution" not in s._join_watch)

# --- arrival meet-up ---
s.remote._summon = {"by": "Revolution", "to": (17, 1627), "channel": "telepath", "t": time.time()}
g.candidates = [(17, 1627)]
g.view = RoomView("Rotting Glade, Trail", {"N"}, [], [], [], time.time()); g.view_seq += 1   # Revolution not here
st.locate_cmd = "pro"
sent.clear(); b._locate_at = 0; b._locate_failed = 0
b._check_arrival_meetup((17, 1627))
check(f"summoner missing: pro + @where ({sent})", "pro" in sent and "/Revolution @where" in sent)
check("…and comeback is now looking for him", "Revolution" in s.comeback.missing)
# arrived and he IS here → no chase, summon cleared
s.remote._summon = {"by": "Revolution", "to": (17, 1627), "t": time.time()}
g.view = RoomView("Rotting Glade, Trail", {"N"}, [], [], ["Revolution"], time.time()); g.view_seq += 1
sent.clear()
b._check_arrival_meetup((17, 1627))
check(f"summoner here: nothing sent, summon cleared ({sent})", not sent and s.remote._summon is None)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
