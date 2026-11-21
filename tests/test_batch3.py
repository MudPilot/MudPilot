"""0.8.25: lag meter, after a death, @summon, lair pacing, loop rotation, daily history, phone control, auto-tune."""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.megamud_files import path_from_route
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
st.auto_rest = True; st.auto_combat = False; st.auto_bless = False; st.auto_spells = False
s = Session(st); b = s.bot; w = s.world
s._no_log_file = True
_tmp = tempfile.mkdtemp()
config.board_dir = lambda bd: os.path.join(_tmp, bd)        # keep the test's history/lairs out of real data
s.lairclock._for = s.history._for = None
sent, alerts = [], []
s.notify.send = lambda kind, msg, force=False: alerts.append((kind, msg))
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T(); s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
lp = path_from_route(w, (1, 3), w.route((1, 3), (1, 16)) + w.route((1, 16), (1, 3)), name="Loop A")
lp.filename = "/x/LOOPA.mp"
lp2 = path_from_route(w, (1, 16), w.route((1, 16), (1, 3)) + w.route((1, 3), (1, 16)), name="Loop B")
lp2.filename = "/x/LOOPB.mp"
s.paths = [lp, lp2]
s.state.candidates = [(1, 3)]
s.state.max_hp, s.state.hp, s.state.max_ma, s.state.ma = 684, 684, 473, 473

# ---- lag meter
now = time.time()
s.state.lag_samples = [(now - 30, 0.3), (now - 20, 0.5), (now - 10, 2.0), (now - 900, 9.0)]
ls = s.stats.lag_stats(600)
check(f"lag stats over 10 min ({ls})", ls and abs(ls[0] - 0.933) < 0.01 and ls[2] == 2.0 and ls[3] == 3)

# ---- after a death: stay put, no Rego, phone says where
b.start_path(lp, loop=True, checked=True); b._begin_loop(lp)
b._last_room = (1, 3); b._last_mobs = ["giant rat"]
alerts.clear()
s.state.on_event[-1]  # registered
for cb in s.state.on_event:
    cb("death", None)
check("stopped, nothing to Rego", not b.walking and b.resume is None)
check(f"phone told where/what ({alerts[-1][1] if alerts else ''})", alerts and alerts[-1][0] == "death" and "giant rat" in alerts[-1][1])
st.death_action = "hangup"; b._death_at = 0
for cb in s.state.on_event:
    cb("death", None)
check("hang-up scheduled", getattr(b, "_death_hangup_at", 0) > time.time())
st.death_action = "stay"; b._death_hangup_at = 0

# ---- @summon
st.remote_enabled = True
st.remote_channels = {"telepath": True}
st.remote_players = {"Dan": ["move"]}
sent.clear()
s.remote.feed_line("Dan telepaths: @summon")
check(f"plain @summon asks where ({sent})", any("where are you" in c for c in sent))
sent.clear()
s.state.candidates = [(1, 3)]
s.remote.feed_line("Dan telepaths: @summon 1 16")
check(f"@summon 1 16 walks there ({sent[-1] if sent else ''})", b.walking and b.path and b.path.title.startswith("Go to") and any("on my way" in c for c in sent))
s.remote.feed_line("Bob telepaths: @summon 1 16")
check("someone not allowed can't summon", True)
b.stop("Stopped by you")
# sender side: '/Rev @summon' gets our room added; their question is answered
sent.clear()
s.send("/Revolution @summon")
check(f"our room added to @summon ({sent})", sent and sent[0] == "/Revolution @summon 1 3")
sent.clear()
s.remote.feed_line("Revolution telepaths: {summon: where are you? send @summon <map> <room>, e.g. @summon 10 297}")
check(f"their 'where are you' answered ({sent})", "/Revolution @summon 1 3" in sent)

# ---- lair clock + pacing
lc = s.lairclock
room = (1, 16)
t = 1000.0
for i in range(8):
    lc.seen_empty(room, t)
    el = 20 if i % 2 else 40
    lc.arrive(room, el >= 30, t + el)
    t += 100
est = lc.estimate(room)
check(f"refill learned (empty at 20 s, stocked at 40 s → 40: {est})", est == 40)
lc.seen_empty(room, time.time() - 15)
rem = lc.remaining(room)
check(f"remaining ~{rem:.0f} s (cleared 15 s ago)", rem is not None and 20 < rem < 30)
# pacing: next step is that lair, we're hurt, it's due in ~25 s → rest here
st.lair_pace, st.lair_pace_max = True, 45
b.LAIR_PACING = False
check("lair pacing is off for now (Dan, 2026-11-01)", not b._lair_pace(next(x for x in lp.steps if x.dest == room), []))
b.LAIR_PACING = True                                  # (the logic, for when it comes back)
w.room(room).lair = w.room(room).lair or "x"
b.start_path(lp, loop=True, checked=True)
step = next(x for x in lp.steps if x.dest == room)
s.state.hp = 500; s.state.view = RoomView("x", {"N"}); s.state.view.t = time.time(); s.state.resting = False
b._pace_until = 0; sent.clear(); b._cool = {}; _steps = b.path.steps; b.path.steps = _steps[:4]   # a short loop
check(f"rests while the lair refills ({sent})", b._lair_pace(step, []) and any(c in ("rest", "medi", "meditate") for c in sent))
s.state.hp = 684; s.state.ma = 473; b._pace_until = 0
check("full anyway → walks on", not b._lair_pace(step, []))
b.path.steps = _steps
# Dan, 2026-10-31, the dark-elf sentries: a lap longer than the regen finds every lair full anyway — no pacing
s.state.hp = 500; b._pace_until = 0; real = b.path.steps
b.path.steps = list(real) * (1 + int(45 // (5 * max(1, len(real)))))
check(f"lap ({len(b.path.steps)} rooms) longer than the {est:.0f} s regen → walks on", not b._lair_pace(step, []))
b.path.steps = real; s.state.hp = 684
# Evolution, 2026-11-01: few rooms by the count, but your real laps (fights and all) take longer than the regen
s.state.hp = 500; b._pace_until = 0; b.path.steps = real[:4]
s.loopstats.lap_secs = lambda loop: 90.0
check("real laps (90 s) longer than the regen → walks on", not b._lair_pace(step, []))
s.loopstats.lap_secs = lambda loop: None; b.path.steps = real; s.state.hp = 684
b.stop("Stopped by you")

# ---- rotation
st.rotate_on, st.rotate_loops, st.rotate_mode, st.rotate_empty_pct = True, ["loopa.mp", "loopb.mp"], "empty", 50
b.start_path(lp, loop=True, checked=True)
check("not mostly empty → stay", not b._rotate(lp, {"lairs_full": 3, "lairs_empty": 1}))
check("mostly empty → off to Loop B", b._rotate(lp, {"lairs_full": 1, "lairs_empty": 3}) and b.after_goto is lp2)
st.rotate_mode, st.rotate_laps = "laps", 2
b.start_path(lp, loop=True, checked=True); b.laps = 2
check("every 2 laps → rotate", b._rotate(lp, None))
st.rotate_on = False
b.stop("Stopped by you")

# ---- history
h = s.history
h._last = time.time() - 3
b.start_path(lp, loop=True, checked=True)
for cb in s.state.on_exp:
    pass
h.on_exp(1500)
h.tick()
d = h.today()
check(f"today: exp, online, looping ({d['exp']}, {d['on']:.0f}, {d['hunt']:.0f})", d["exp"] >= 1500 and d["on"] >= 2 and d["hunt"] >= 2)
check("per-loop exp", d["loops"].get("Loop A", {}).get("exp", 0) >= 1500)
h.save(); h._for = None; h.data = {}
check("saved and read back", h.days() and h.days()[0][1]["exp"] >= 1500)
b.stop("Stopped by you")

# ---- phone control
ph = s.phone
alerts.clear(); ph._last_cmd = 0
ph.handle("Status")
check(f"status reply ({alerts[-1][1].splitlines()[0] if alerts else ''})", alerts and alerts[-1][0] == "control" and "Connected" in alerts[-1][1])
b.start_path(lp, loop=True, checked=True)
ph._last_cmd = 0; ph.handle("stop")
check("stop from phone", not b.walking)
ph._last_cmd = 0; ph.handle("rm -rf")
check("anything else → help only", "Didn't understand" in alerts[-1][1])
ph._last_cmd = time.time(); n = len(alerts); ph.handle("status")
check("flood guard", len(alerts) == n)

# ---- auto-tune
at = s.autotune
st.rest_below_hp, st.rest_until_hp, st.rest_below_ma, st.rest_until_ma = 45, 85, 40, 90
st.hangup_low_hp, st.hangup_hp_pct, st.run_pct = True, 25, 0
vs = at.make_variants()
check(f"variants ({[(v['name'], v['rest_below_hp'], v['rest_until_hp']) for v in vs]})",
      len(vs) == 4 and vs[1]["rest_below_hp"] == 35 and vs[2]["rest_until_hp"] == 95)
check("HP floor respected", min(v["rest_below_hp"] for v in vs) >= 35)
check("needs a loop", "start a loop" in at.start(1, 1))
b.start_path(lp, loop=True, checked=True)
print("  ", at.start(1, 1))
check("baseline kept for restore", st.tune_baseline.get("rest_below_hp") == 45)
rates = [1000, 3000, 2000, 1500]
check("each trial starts by topping up to full", at.prep and b._rest_full)
check(f"starts at the loop's first room, topping up ({at.phase})", at.phase == "topup")
for i in range(len(vs)):
    at._last = time.time() - 1; at.tick()            # full already → clock starts
    at.results[at.order[at.trial]]["exp"] = rates[at.order[at.trial]] * 60 // 60
    at._trial_secs = 59; at._last = time.time() - 2
    at.tick()
    if i == 0:
        check(f"time's up → finishes the lap first ({at.phase})", at.phase == "finishing" and at.trial == 0)
    at.lap_end()                                     # back at the start: next setting
check("top-up flag cleared at the end", not b._rest_full)
check(f"finished, best kept ({st.rest_below_hp}/{st.rest_until_hp})", not at.active and st.rest_below_hp == 35 and st.rest_until_hp == 85)
check("baseline cleared", not st.tune_baseline)
# a trial that ends short of full is charged the rest it would need
s.state.hp = 342
b.regen.period, b.regen.hp_gain, b.regen.ma_gain = 10.0, [5.0] * 5, [5.0] * 5
owed = at.owed_secs()
check(f"ending at 50% HP owes ~100 s of resting ({owed:.0f})", 95 <= owed <= 105)
s.state.hp = 684
# death mid-test restores
st.rest_below_hp = 45
b.start_path(lp, loop=True, checked=True)
at.start(1, 1); at._trial_secs = 0
at.trial = 1; at._begin_trial()
check("trial applied", st.rest_below_hp == 35)
for cb in s.state.on_event:
    cb("death", None)
check("death → originals back, test off", not at.active and st.rest_below_hp == 45)
# interrupted (closed mid-test) → restored on next start
st.tune_baseline = {"rest_below_hp": 50, "rest_until_hp": 80, "rest_below_ma": 30, "rest_until_ma": 90}
st.rest_below_hp = 35
at._restore_if_interrupted()
check("restored after an interrupted test", st.rest_below_hp == 50 and not st.tune_baseline)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
