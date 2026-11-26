"""0.8.227.7 (Dan: "pile up and sell when the party's full"). Miserable and Revolution pile up runed stone cudgels on
the loop; once neither has room for another, the whole party walks to the shop (Exquisite Weaponry is ~220 rooms
away — past the 60-step trip limit), both sell theirs (each down to its own 'keep'), and they walk back."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_party_full_sell"))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

WORLD = os.path.join(here, "mudpilot", "bundled", "Paradigm.db")
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False

def make(name):
    st = config.Settings(); st.save = lambda: None; st.my_name = name; st.party_sync = True
    s = Session(st, world_path=WORLD); s._no_log_file = True
    s.telnet = Tel(); s._entered = True
    sent = []
    s.send = lambda c, from_bot=False: sent.append(c)
    s.log = lambda m, *a, **k: sent.append("LOG " + m)
    return s, st, sent

# ---------------------------------------------------------------- the leader
s, cfg, sent = make("Miserable")
g, tr, ps = s.state, s.trips, s.partysync
cfg.auto_sell_on, cfg.auto_sell_items, cfg.auto_sell_party_full, cfg.trip_max_steps = True, ["runed stone cudgel"], True, 5
cfg.auto_deposit_on = cfg.auto_buy_on = False
shops = tr.sell_shops("runed stone cudgel")
check(f"a shop buys cudgels ({shops[:2]})", bool(shops))
start = (14, 6538)
g.candidates = [start]
rt = s.bot.plan_route(start, shops[0]) if shops else None
check(f"…far from the loop ({len(rt) if rt else rt} steps, limit 5)", rt and len(rt) > 5)
g.carrying = "6 runed stone cudgels, 300 gold crowns"
g.party = {"Miserable": {}, "Revolution": {}}
g.enc = (1950, 2000, "Heavy", 97)                    # 50 free: a cudgel (80) won't fit
ps.peers = {"Revolution": {"me": {"free": 300}}}
check("Revolution still has room: no trip", tr.next_trip() is None and not tr.party_full())
ps.peers["Revolution"]["me"]["free"] = 40
check("both full: party_full", tr.party_full())
t = tr.next_trip()
check(f"…a sell trip, past the step limit ({t and t[:2]})", t and t[0] == "sell" and t[1] in shops)
check(f"…sells the 6 cudgels ({t and t[2]})", t and t[2].count("sell runed stone cudgel") == 6)
g.enc = (1000, 2000, "Medium", 50)
check("my own pack has room: no trip", tr.next_trip() is None)
cfg.auto_sell_party_full = False; g.enc = (1950, 2000, "Heavy", 97); ps.peers["Revolution"]["me"]["free"] = 300
check("switch off: the normal 5-step limit holds (no shop that near)", tr.next_trip() is None)
cfg.auto_sell_party_full = True; ps.peers["Revolution"]["me"]["free"] = 40

# the leader at the shop: sells, tells Revolution, waits for 'sold', then back to the loop
shop = t[1]
back = []
s.bot.start_path = lambda mp, loop=True, checked=True: back.append(mp)
g.candidates = [shop]
g.view = type("V", (), {"name": "Exquisite Weaponry", "players": ["Revolution"], "monsters": []})()
mp = type("MP", (), {"title": "Cudgel loop"})()
sent.clear()
check("trip started at the shop", tr.start_trip(mp, *t) and tr.trip["party"])
def run(n=60):
    for _ in range(n):
        if not tr.trip:
            break
        tr.trip["next_at"] = 0
        tr.tick()
run(12)
check(f"leader sold its 6 ({sum(c == 'sell runed stone cudgel' for c in sent)})",
      sum(c == "sell runed stone cudgel" for c in sent) == 6)
check(f"…told Revolution to sell theirs", "/Revolution @mpsync sell runed stone cudgel" in sent)
check("…and waits for them", tr.trip is not None and not back)
ps.command("Revolution", "sold")
run(3)
check(f"Revolution sold: back to the loop ({back})", tr.trip is None and back == [mp])

# ---------------------------------------------------------------- the follower
f, fcfg, fsent = make("Revolution")
fcfg.item_rules = ["runed stone cudgel: get, stash, keep 1"]
f.state.candidates = [shop]
f.state.party = {"Miserable": {}, "Revolution": {}}
f.state.carrying = "4 runed stone cudgels, a log raft"
f.state.enc = (1990, 2000, "Heavy", 99)
check(f"follower tells its room in party sync ({f.partysync.my_info()})", "free=10" in f.partysync.my_info())
f.partysync.command("Miserable", "sell runed stone cudgel")
check("follower reads its pack first", "i" in fsent and f.trips.trip and f.trips.trip["phase"] == "count")
f.trips.trip["next_at"] = 0
for _ in range(12):
    if not f.trips.trip:
        break
    f.trips.trip["next_at"] = 0
    f.trips.tick()
check(f"…sells down to its keep of 1 ({sum(c == 'sell runed stone cudgel' for c in fsent)})",
      sum(c == "sell runed stone cudgel" for c in fsent) == 3)
check("…and tells the leader it's done", fsent[-1] == "/Miserable @mpsync sold" and f.trips.trip is None)

# party sync: 'free' re-sends only on a 50-step change, not every pickup
f.partysync.peers = {"Miserable": {"me": {"lvl": 52}}}
f.partysync.asked = {"miserable"}
f.state.level = 52
fsent.clear(); f.partysync._me_checked = 0; f.partysync._told_me = {}
f.partysync.tick()
n1 = sum("@mpsync me" in c for c in fsent)
f.state.enc = (1995, 2000, "Heavy", 99)
fsent.clear(); f.partysync._me_checked = 0
f.partysync.tick()
n2 = sum("@mpsync me" in c for c in fsent)
f.state.enc = (1700, 2000, "Heavy", 85)
fsent.clear(); f.partysync._me_checked = 0
f.partysync.tick()
n3 = sum("@mpsync me" in c for c in fsent)
check(f"'free' goes out, not again for 5 less, again after selling ({n1}, {n2}, {n3})", (n1, n2, n3) == (1, 0, 1))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
