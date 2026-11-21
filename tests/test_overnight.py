"""0.8.23: regen tick, up-on-tick, top-off, mana throttle, rest diagnosis, attack on entry,
leader gone / left behind, stuck watchdog, morning summary."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.regenclock import RegenClock
from mudpilot.megamud_files import path_from_route
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
st.auto_rest = True; st.use_meditate = True; st.auto_combat = False; st.auto_bless = False; st.auto_spells = False
st.rest_below_hp, st.rest_until_hp, st.rest_below_ma, st.rest_until_ma = 75, 85, 40, 90
s = Session(st); b = s.bot; w = s.world
s._no_log_file = True
sent = []
alerts = []
s.notify.send = lambda kind, msg, force=False: alerts.append((kind, msg))
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T()
s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

# ---- regen clock learns period and gain
rc = RegenClock()
t0 = 1000.0
rc.feed(True, 500, 684, 200, 336, now=t0)           # sat down
hp, ma = 500, 200
for i in range(1, 6):
    hp += 20; ma += 10
    rc.feed(True, hp, 684, ma, 336, now=t0 + 2 + i * 10)
check(f"tick period learned ({rc.period})", rc.learned and abs(rc.period - 10) < 0.01)
check(f"gain learned ({rc.gain('hp'):.2f}% HP)", abs(rc.gain("hp") - 100 * 20 / 684) < 0.01)
check("heal isn't a tick", not rc.feed(True, hp + 100, 684, ma, 336, healed_recently=True, now=t0 + 70))

# ---- up on the tick: 1% short of rest-until, tick just landed → get up
b.regen = rc
rc.last_tick = time.time()
s.state.max_hp, s.state.max_ma = 684, 336
s.state.hp, s.state.ma = int(684 * 0.84), int(336 * 0.95)
s.state.resting = True
b._rest_end = None
check("1% short right after a tick → up", b._up_on_tick())
s.state.hp = int(684 * 0.80)
check("5% short → keep resting", not b._up_on_tick())
rc.last_tick = time.time() - 6
s.state.hp = int(684 * 0.845)
check("not right after a tick → keep resting", not b._up_on_tick())

# ---- top-off: topped, one tick from full, solo → one more tick
rc.last_tick = time.time()
s.state.party = {}
s.state.hp, s.state.ma = int(684 * 0.98), int(336 * 0.99)
s.state.view = RoomView("x", {"N"}); s.state.view.t = time.time()
b._topoff, b._topoff_used = None, False
check("one tick from full → takes it", b._topoff_one_more())
check("…only once per rest", (setattr(b, "_topoff", None) or True) and not b._topoff_one_more())
b._topoff, b._topoff_used = None, False
s.state.party = {"Miserable": {}, "Revolution": {}}
check("in a party → no top-off", not b._topoff_one_more())
s.state.party = {}

# ---- mana throttle
st.auto_spells = False
st.attack_spells = ["mmis"]
sp = {"Number": 1, "Name": "magic missile", "Short": "mmis", "ManaCost": 5}
s.spellbook.find = lambda x: sp if x == "mmis" else None
s.state.resting = False
s.state.ma = int(336 * 0.50)
check("50% mana with rest at 40 + band 15 → saving", b.mana_saving())
s.state.ma = int(336 * 0.80)
check("80% mana → not saving", not b.mana_saving())
s.state.ma = int(336 * 0.35)
check("35% mana (rest at 40) but 3 cheap casts left → can wait", b.mana_rest_can_wait())
s.state.ma = int(336 * 0.15)
check("15% mana → rest now", not b.mana_rest_can_wait())
st.mana_throttle = False
s.state.ma = int(336 * 0.35)
check("throttle off → rests at 40", not b.mana_rest_can_wait())
st.mana_throttle = True

# ---- rest diagnosis: why, how long, interruptions merged
ss = s.stats
s.state.resting = False; ss._was_resting = False
b._rest_reason = "mana below 40% (31%)"
s.state.resting = True; ss._rest_track(100.0); ss._was_resting = True
s.state.resting = False; ss._rest_track(130.0); ss._was_resting = False
s.state.resting = True; ss._rest_track(132.0); ss._was_resting = True     # back down 2 s later: same rest
b._rest_end = "topped up"
s.state.resting = False; ss._rest_track(160.0); ss._was_resting = False
ss._rest_track(170.0)
r = ss.rest_log[-1] if ss.rest_log else {}
check(f"one rest logged, 60 s, interrupted once ({r.get('secs')}, {r.get('breaks')})",
      len(ss.rest_log) == 1 and r.get("secs") == 60 and r.get("breaks") == 1)
check("why + how it ended kept", r.get("why", "").startswith("mana below 40%") and r.get("ended") == "topped up")
sm = ss.rest_summary()
check(f"summary groups by reason ({sm})", sm and sm[0][0] == "mana below 40%" and sm[0][1] == 1)

# ---- attack on entry: fresh room with a hostile → attack before party check / blesses
st.auto_combat, st.attack_on_entry = True, True
st.attack_spells = []
rec = next(m for m in w.monsters.values() if m["exp"] > 0 and int(m.get("align") or 0) in (1, 2, 5, 6))
s.state.view = RoomView("x", {"N"}, monsters=[(rec["name"], rec)]); s.state.view.t = time.time()
s.state.view_seq += 1
s.state.in_combat = False
s.state.hp = 684
sent.clear()
b._cool = {"attack": time.time()}            # cooldown would normally hold the attack for 2 s
b._entry_attack(b.attackable(), True, False)
check(f"attacked on entry despite cooldown ({sent})", any(c.startswith("a ") or c.startswith("attack") for c in sent))
sent.clear()
check("not twice for the same room view", not b._entry_attack(b.attackable(), True, False))
st.auto_combat = False

# ---- leader gone
x = b.x
x._following = "Revolution"
x.note_line("Revolution just disconnected!!!")
check(f"leader drop noticed ({x.leader_gone})", x.leader_gone and "Revolution" in x.leader_gone)
check("phone told", any(k == "leader" for k, _ in alerts))
x.note_line("Revolution just entered the Realm.")
check("back in → cleared", not x.leader_gone)
# left behind
s.state.view = RoomView("x", {"N"}, players=["Revolution"]); s.state.view.t = time.time()
b.walking = False
x.leader_watch()
check("leader here → fine", not x.leader_gone)
s.state.view = RoomView("y", {"S"}, players=[]); s.state.view.t = time.time()
x.leader_watch(); x._behind_since = time.time() - 40
sent.clear(); x.leader_watch()
check(f"left behind → noticed, @wait sent ({sent})", x.leader_gone and "/Revolution @wait" in sent)
# a pitch-black room shows nobody: that's not being left behind (Revolution, 2026-11-06, the Frozen Cavern's Dark Hole)
x._left_behind = None; x._behind_since = 0
s.state.view = RoomView("(dark)", {"D"}, players=[]); s.state.view.t = time.time()
x.leader_watch(); x._behind_since = time.time() - 40 if x._behind_since else 0
sent.clear(); x.leader_watch()
check(f"pitch black, nobody shown → not 'left behind' ({sent})", not x.leader_gone and not sent)
x._following = None; x._followed = None; x._left_behind = None

# ---- watchdog: stuck on a loop → nudges, then gives up after 3
st.watchdog_on, st.watchdog_mins = True, 1
wd = s.watchdog
lp = path_from_route(w, (1, 3), w.route((1, 3), (1, 16)) + w.route((1, 16), (1, 3)), name="L")
s.state.candidates = [(1, 3)]
b.start_path(lp, loop=True, checked=True)
alerts.clear()
for i in range(3):
    wd._moving()
    wd._progress_t = time.time() - 120
    wd.tick()
    b._watchdog_rego_at = time.time() - 1
    wd.after_tick()
check(f"nudged 3 times, back walking ({len(wd.tries)})", len(wd.tries) == 3 and b.walking)
wd._moving(); wd._progress_t = time.time() - 120
wd.tick()
check("4th → gives up, stopped, phone told", wd.gave_up and not b.walking and any("gave up" in m or "Tried 3" in m for _, m in alerts))
# your stop is never undone
wd.gave_up, wd.tries = False, []
b.start_path(lp, loop=True, checked=True)
b.stop("Stopped by you")
wd._progress_t = time.time() - 999
wd.tick(); b._watchdog_rego_at and wd.after_tick()
check("your Stop is left alone", not b.walking)
st.watchdog_on = False

# ---- morning summary
wd.since = time.time() - 6 * 3600
wd.tot_exp, wd.tot_kills, wd.tot_deaths = 9_000_000, 2500, 1
txt = wd.summary_text()
check(f"summary text ({txt.splitlines()[0]})", "9,000,000 exp" in txt and "1,500k/hr" in txt and "1 deaths" in txt)
st.summary_on, st.ntfy_on = True, True
st.summary_time = time.strftime("%H:%M", time.localtime(time.time() - 60))
alerts.clear(); wd._summary_day = None
wd._summary_tick(time.time())
check("sent at the set time", any(k == "summary" for k, _ in alerts))
alerts.clear(); wd._summary_tick(time.time())
check("only once a day", not alerts)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
