"""0.8.200 auto-train (training.py, from the MudPlay review): a banked level → the nearest trainer for this class and
level at the end of a lap (MME Shops ShopType 8: ClassRest, the level band, MaxLVL 999 placeholders skipped), the fee
(bank first when short), 'train' while levels are banked (Stock's and Paradigm's success lines), every refusal line,
then back to the loop. Party training (@ptrain): members' stops first, the leader's last, re-invites, and comeback
leaves a training trip alone. All off by default."""
import os, sys, time, types
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, expcalc as X
from mudpilot.session import Session
from mudpilot import training as T
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

st = config.Settings(); st.save = lambda: None; st.board = "Paradigm"
check("everything off by default", st.auto_train is False and st.train_stats is False and st.party_train is False
      and st.train_keep_levels == 0 and st.train_max_level == 0 and st.train_stats_plan == "")

sent, raw = [], []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def send_raw(self, b): raw.append(b.decode("cp437"))
    def close(self): pass

def make(name):
    st = config.Settings(); st.save = lambda: None; st.board = "Paradigm"; st.my_name = name
    s = Session(st); s._no_log_file = True
    s.telnet = Tel(); s._entered = True
    s.log = lambda m, *a, **k: logs.append(m)
    return s, st
logs = []
s, st = make("Miserable")
b, w, g, Tr = s.bot, s.world, s.state, s.training
g.char_class, g.race, g.level, g.in_combat, g.resting = "Mage", "Human", 7, False, False

# --- fee
check(f"fee: level 7 at 0% markup = 350 copper ({T.fee(7, 0)})", T.fee(7, 0) == 350)
check(f"fee: level 10 at 300% markup = 2000 ({T.fee(10, 300)})", T.fee(10, 300) == 2000)
check(f"fee: level 15 at 2500% = {T.fee(15, 2500)}", T.fee(15, 2500) == int(15 * 5 * 2600 / 100) * 10)

# --- which trainers
sh = w.shops
mage = T.class_num(w, "Mage")
check("Mage Training Room serves a level 5 mage", T.serves(sh[28], mage, 5))
check("…not a level 5 warrior (class restriction)", not T.serves(sh[28], T.class_num(w, "Warrior"), 5))
check("…not at level 10 (MaxLVL 10 <= level: it trains up to 10)", not T.serves(sh[28], mage, 10))
check("Super Mage Trainer (11..11) serves level 10 → 11", T.serves(sh[62], mage, 10))
check("…but not level 11, nor level 8 (MinLVL 11 > 9)", not T.serves(sh[62], mage, 11) and not T.serves(sh[62], mage, 8))
check("High Level Trainer (12..20, any class) serves level 11", T.serves(sh[64], mage, 11))
check("MaxLVL 999 placeholder rows are skipped", not T.serves(sh[160], mage, 80) and not T.serves(sh[39], mage, 5))
check("a trainer MME marks not in the game is skipped", not T.serves(sh[165], mage, 5))
check("stats only: the band doesn't matter, the class does",
      T.serves(sh[28], mage, 40, stats_only=True) and not T.serves(sh[14], mage, 3, stats_only=True))
opts = T.trainers(w, mage, 5)
rooms = {o[0] for o in opts}
check(f"level 5 mage trainers: Mage Training Room, the any-class Training Room, Hydra ({sorted(rooms)})",
      {(1, 399), (1, 1376), (1, 2147), (14, 1792), (12, 2249)} <= rooms and (1, 497) not in rooms)
pick = T.pick_trainer(opts, {(1, 399): 12, (1, 1376): 5, (1, 2147): 40, (14, 1792): 5})
check(f"nearest wins, the cheaper markup breaks a tie ({pick})", pick and pick[0] == (1, 1376))
check("too far = not picked", T.pick_trainer(opts, {(1, 399): 900}, limit=300) is None)
Tr._dist_from = lambda here: {(1, 399): 12, (1, 1376): 30, (14, 1792): 3}
g.candidates = [(1, 300)]
check(f"choose(): the nearest trainer that serves us ({Tr.choose(mage, 5)})", Tr.choose(mage, 5)[0] == (14, 1792))
Tr.bad_rooms[(14, 1792)] = 5
check("a room that refused us at this level is skipped", Tr.choose(mage, 5)[0] == (1, 399))
Tr.bad_rooms.clear()

# --- the CP plan text
rows = T.parse_plan("10: STR 60 AGL 50; 20: STR 70 INT 40\nlevel 5: HEA 55")
check(f"plan parsed and sorted ({rows})", rows == [(5, {"HEA": 55}), (10, {"STR": 60, "AGL": 50}),
                                                   (20, {"STR": 70, "INT": 40})])
check(f"row at level 15: rows at or below merged ({T.plan_row(rows, 15)})",
      T.plan_row(rows, 15) == {"HEA": 55, "STR": 60, "AGL": 50})
check("row at level 4: nothing", T.plan_row(rows, 4) == {})
check("plan text round-trips", T.parse_plan(T.format_plan(rows)) == rows)

# --- level due: the exp line + "You gain", the reserve and the ceiling
chart = X.chart_for(w, "Mage", "Human")
check("never seen the exp line: unknown", Tr.banked() is None and Tr.levels_to_train() == 0)
g.exp_line_at = time.time()
g.exp_total = X.exp_needed(7, chart)
g.exp_needed = X.exp_needed(8, chart) - g.exp_total
g._exp_since_line = g.exp_needed - 1
check("one exp short: nothing banked", Tr.banked() == 0)
g._exp_since_line = X.exp_needed(10, chart) - g.exp_total + 5
check(f"exp for level 10 at level 7: 3 banked ({Tr.banked()})", Tr.banked() == 3)
check("…all 3 to train", Tr.levels_to_train() == 3)
st.train_keep_levels = 1
check(f"keep 1 banked: 2 to train ({Tr.levels_to_train()})", Tr.levels_to_train() == 2)
st.train_max_level = 8
check(f"don't train above 8: 1 ({Tr.levels_to_train()})", Tr.levels_to_train() == 1)
st.train_max_level = 7
check("don't train above 7: none", Tr.levels_to_train() == 0)
st.train_keep_levels, st.train_max_level = 0, 0
g.race = "Nowhere"
check("no exp chart: one at a time", Tr.banked() == 1)
g.race = "Human"

# --- lap end: off by default, followers never, not in combat / Hands off
calls = []
b.goto = lambda room, then=None, ask=None: calls.append(("goto", room)) or True
b.start_path = lambda mp, loop=None, checked=False: calls.append(("loop", mp.title)) or True
mp = types.SimpleNamespace(title="Test Loop", steps=[])
g.wealth = 10 ** 6
check("setting off: no trip", Tr.lap_end(mp) is False and Tr.trip is None)
st.auto_train = True
b.x._following = "Revolution"
check("a follower never sets off on its own", Tr.lap_end(mp) is False and Tr.trip is None)
b.x._following = None
g.in_combat = True
check("never in combat", Tr.lap_end(mp) is False)
g.in_combat = False
st.hands_off = True
check("never with Hands off on", Tr.lap_end(mp) is False)
st.hands_off = False
check("solo, levels banked: off to the trainer", Tr.lap_end(mp) is True and Tr.trip is not None)
check(f"…the nearest one ({calls})", calls[-1] == ("goto", (14, 1792)))

# --- at the trainer: exp + i, train, success lines (both realms), again while banked
g.candidates = [(14, 1792)]
b.walking = False
Tr.tick()
check(f"arrived: at the stop ({Tr.trip['phase']})", Tr.trip["phase"] == "at_stop")
Tr.tick()
check("our own train starts", Tr.me is not None and Tr.me["phase"] == "check")
sent.clear()
Tr.tick()
check(f"reads exp and the purse first ({sent})", sent[-2:] == ["exp", "i"])
Tr.me["deadline"] = 0; Tr.me["next_at"] = 0
Tr.tick()
check(f"train sent ({sent[-1:]})", sent[-1:] == ["train"] and Tr.me["phase"] == "train_wait")
fee_ = Tr.me["fee"]
check(f"Hydra Trainer fee: level 7 at 9999% ({fee_})", fee_ == T.fee(7, 9999))
w0 = g.wealth
Tr.note_line("[HP=100/MA=50]:You hand over 5 platinum pieces and you receive training to attain level 8!")
Tr.tick()
check(f"Stock success: level 8 ({g.level}), the fee left the purse ({g.wealth})", g.level == 8 and g.wealth == w0 - fee_)
check("…and it looks / reads exp again", Tr.me["phase"] == "check" and "" in sent)
Tr.me["next_at"] = 0; Tr.tick(); Tr.me["deadline"] = 0; Tr.me["next_at"] = 0; Tr.tick()
check("still banked: train again", sent[-1] == "train" and Tr.me["phase"] == "train_wait")
Tr.note_line("You hand over 6 platinum pieces to train to the next level.")
Tr.tick()
check(f"Paradigm success (no number): current + 1 = 9 ({g.level})", g.level == 9)
Tr.me["next_at"] = 0; Tr.tick(); Tr.me["deadline"] = 0; Tr.me["next_at"] = 0; Tr.tick()
Tr.note_line("You hand over 7 platinum pieces to train to the next level.")
Tr.tick()
check(f"three banked levels trained ({g.level})", g.level == 10)
Tr.me["next_at"] = 0; Tr.tick(); Tr.me["deadline"] = 0; Tr.me["next_at"] = 0; Tr.tick()
check("nothing more banked: the counter's done", Tr.me is None)
for _ in range(3):
    Tr.tick()
check(f"…and back to the loop ({calls[-1]})", Tr.trip is None and calls[-1] == ("loop", "Test Loop"))

# --- each refusal line
def at_counter(level=7):
    g.level = level
    g.exp_total = X.exp_needed(level, chart)
    g.exp_needed = X.exp_needed(level + 1, chart) - g.exp_total
    g._exp_since_line = g.exp_needed + 1
    g.wealth = 10 ** 6
    res = []
    Tr._me_start(0, on_done=lambda n, why: res.append((n, why)))
    Tr.me.update(sent=True, deadline=0, next_at=0, exp_at=-1, inv_seq=-1)
    Tr.tick()
    return res
for line, kind in (("You must be in an appropriate training room to train!", "room"),
                   ("This shop is not suitable for your training.", "unsuitable"),
                   ("You have not progressed far enough to use the training provided here.", "too_low"),
                   ("You have progressed too far to use the training provided here.", "too_high"),
                   ("You may not train any further.  Please contact your sysop", "maxed"),
                   ("You do not have the required experience to train yet!", "no_exp"),
                   ("You do not have the money required for your training.", "no_money")):
    Tr.maxed = False
    Tr.bad_rooms.clear()
    res = at_counter()
    assert Tr.me and Tr.me["phase"] == "train_wait", Tr.me
    Tr.note_line(line)
    Tr.tick()
    extra = ""
    good = res and res[0] == (0, kind) and Tr.me is None and g.level == 7
    if kind in ("room", "unsuitable", "too_low", "too_high"):
        good = good and Tr.bad_rooms.get((14, 1792)) == 7
        extra = " — that trainer's skipped at this level"
    elif kind == "maxed":
        good = good and Tr.maxed and Tr.levels_to_train() == 0
        extra = " — no more training this session"
    elif kind == "no_exp":
        good = good and Tr.banked() == 0
        extra = " — the estimate's dropped till the next exp line"
    elif kind == "no_money":
        good = good and sent[-1] == "i"
        extra = " — the purse is read again"
    check(f"refusal '{line[:40]}…' → {kind}{extra}", good)
Tr.maxed = False
Tr.bad_rooms.clear()
res = at_counter()
Tr.me["sent_at"] = time.time() - 9
Tr.tick()
check("no answer in 8 s: settles", res == [(0, "no answer")] and Tr.me is None)

# --- short of the fee: no train, the bank (shoptrips withdraw) first
g.level, g.wealth = 7, 100
res = []
Tr._me_start(9999, on_done=lambda n, why: res.append((n, why)))
Tr.me.update(sent=True, deadline=0, next_at=0, exp_at=-1, inv_seq=-1)
sent.clear()
Tr.tick()
check(f"purse short: 'train' not sent ({res})", "train" not in sent and res == [(0, "no_money")])
wd = []
s.trips.withdraw_for = lambda mp, loop, short, why="", after=None: wd.append((short, why, after)) or True
Tr.trip = None
g.candidates = [(1, 300)]
Tr._dist_from = lambda here: {(14, 1792): 3}
Tr.mute_until = 0
check("lap end short of the fee: off", Tr.lap_end(mp))
check(f"…to the bank first, for the fees of every banked level ({wd[:1] and wd[0][:2]})",
      wd and wd[0][0] == T.fee(7, 9999) - 100 and wd[0][1] == "training" and Tr.trip["phase"] == "bank")
calls.clear()
wd[0][2]()
check(f"…then on to the trainer ({calls})", calls == [("goto", (14, 1792))] and Tr.trip["phase"] == "going")
Tr.cancel("test")

# --- 'progressed too far': on to the next trainer that serves us
g.wealth, g.level = 10 ** 6, 7
g.exp_total = X.exp_needed(7, chart); g.exp_needed = X.exp_needed(8, chart) - g.exp_total
g._exp_since_line = g.exp_needed + 1
g.candidates = [(1, 300)]
Tr._dist_from = lambda here: {(14, 1792): 3, (1, 399): 9}
Tr.mute_until = 0
calls.clear()
assert Tr.lap_end(mp) and calls[-1] == ("goto", (14, 1792))
g.candidates = [(14, 1792)]
Tr.tick(); Tr.tick(); Tr.tick()
Tr.me.update(deadline=0, next_at=0); Tr.tick()
assert Tr.me["phase"] == "train_wait"
Tr.note_line("You have progressed too far to use the training provided here.")
Tr.tick()
check(f"'progressed too far' → walks on to the next trainer ({calls[-1]})",
      calls[-1] == ("goto", (1, 399)) and Tr.trip and Tr.trip["phase"] == "going")
Tr.cancel("test")
Tr.bad_rooms.clear()

# --- Stop ends it
g.wealth = 10 ** 6
Tr.mute_until = 0
assert Tr.lap_end(mp)
b._user_stop_at = time.time() + 1
Tr.tick()
check("your Stop ends the trip (no going back by itself)", Tr.trip is None)
b._user_stop_at = 0

# --- party: the leader
sent.clear()
s.state.party = {"Miserable": {"t": time.time()}, "Revolution": {"t": time.time()}, "Megaman": {"t": time.time()}}
s.partysync.peers = {"Revolution": {"rest": 0, "hp": 100, "ma": 100, "t": time.time()}}
st.party_train = True
druid = T.class_num(w, "Druid")
check("MudPilot members: only those that talk mpsync", Tr.mudpilot_members() == ["Revolution"])
Tr.in_party_since = {"Revolution": time.time() - 30}
Tr._ask_members()
check(f"asks a member who's been with us 20 s ({sent})", "/Revolution @ptrain ask" in sent)
Tr.party_msg("Revolution", f"st s=r l=5 c={druid} n=1 cash=100000")
check(f"his status read ({Tr.peers.get('Revolution')})", Tr.ready_members() == ["Revolution"])
Tr._dist_from = lambda here: {(1, 501): 10, (1, 504): 12, (1, 399): 3, (1, 1376): 8}
stops, notes = Tr.plan_stops((1, 300), 1, ["Revolution"])
check(f"stops: his (druid room / any-class room, nearest) first, mine last ({[(x['room'], x['members'], x['me']) for x in stops]})",
      len(stops) == 2 and stops[0]["members"] == ["Revolution"] and stops[0]["room"] == (1, 1376)
      and stops[-1]["me"] and stops[-1]["room"] == (1, 399))
Tr.party_msg("Revolution", f"st s=r l=5 c={druid} n=1 cash=10")
stops, notes = Tr.plan_stops((1, 300), 1, ["Revolution"])
check(f"a member who can't pay his own fee is left out ({notes})",
      all(not x["members"] for x in stops) and "left out" in notes[0])
Tr.party_msg("Revolution", f"st s=r l=5 c={druid} n=1 cash=100000")
sent.clear(); calls.clear()
g.candidates = [(1, 300)]
g.level = 7
g.exp_total = X.exp_needed(7, chart); g.exp_needed = X.exp_needed(8, chart) - g.exp_total
g._exp_since_line = 0                         # leader not due: only Revolution trains
Tr.mute_until = 0
check("a ready member starts a trip on its own", Tr.lap_end(mp))
check(f"…'trip on' to the MudPilot member only ({sent})", "/Revolution @ptrain trip on" in sent
      and not any("Megaman" in c for c in sent))
check("comeback leaves members on a training trip alone", s.comeback._training("Revolution"))
s.comeback.feed_line("Revolution just left the Realm.")
check("'Revolution just left the Realm.' → not missing", "Revolution" not in s.comeback.missing)
g.candidates = [(1, 1376)]
Tr.tick()
sent.clear()
Tr.tick()
check(f"at his trainer: he's told to train ({sent})", "/Revolution @ptrain train 6 1/1376" in sent)
s.remote.handle("telepath", "Revolution", "@ptrain done 1 trained")
Tr.tick()
Tr.tick()
check(f"his done → invited back ({sent[-1]})", sent[-1] == "invite Revolution")
Tr.tick()
Tr.note_line("Revolution started to follow you.")
for _ in range(3):
    Tr.tick()
check("rejoined → no more stops (not training myself) → done", Tr.trip is None)
check(f"…'trip off' and back to the loop ({sent[-3:]}, {calls[-1]})", "/Revolution @ptrain trip off" in sent
      and calls[-1] == ("loop", "Test Loop"))

# leader trains too: the party is invited back after (training disbanded it)
g._exp_since_line = g.exp_needed + 1
Tr.party_msg("Revolution", f"st s=w l=6 c={druid} n=0 cash=100000")
g.candidates = [(14, 1792)]
Tr._dist_from = lambda here: {(14, 1792): 0}
Tr.mute_until = 0
sent.clear()
assert Tr.lap_end(mp)
Tr.tick()
check("leader's own stop: trains itself", Tr.me is not None)
Tr.me = None
Tr._after_my_train(1, "all banked levels trained")
s._party_sent = {}                            # (the session drops a repeat invite within 8 s)
sent.clear()
Tr.tick()
check(f"after its own train: everyone invited back ({sent})", "invite Revolution" in sent and "invite Megaman" in sent)
Tr.note_line("Revolution started to follow you.")
Tr.note_line("Megaman is now following you.")
for _ in range(2):
    Tr.tick()
check("all back → done", Tr.trip is None)

# --- party: the member
s2, st2 = make("Revolution")
T2 = s2.training
g2 = s2.state
g2.char_class, g2.race, g2.level, g2.in_combat = "Druid", "Human", 5, False
st2.auto_train = True
s2.bot.x._following = "Miserable"
sent.clear()
T2.party_msg("Miserable", "ask")
check(f"member, party training off: ignores ask ({sent})", not sent)
st2.party_train = True
T2.party_msg("Miserable", "ask")
check(f"never seen exp: reads it first ({sent})", sent == ["exp"])
c2 = X.chart_for(s2.world, "Druid", "Human")
g2.exp_line_at = time.time(); g2.exp_total = X.exp_needed(5, c2); g2.exp_needed = 10; g2._exp_since_line = 20
g2.wealth = 5000
T2.tick()
check(f"…then answers ({sent[-1]})", sent[-1] == f"/Miserable @ptrain st s=r l=5 c={druid} n=1 cash=5000")
sent.clear()
T2.party_msg("Megaman", "train 6 1/1376")
check("orders from anyone but the leader are ignored", not sent and T2.me is None)
T2.party_msg("Miserable", "trip on")
check("'trip on': comeback held", T2.holding_comeback() and s2.comeback._training())
s2.state.party = {"Miserable": {"t": time.time()}, "Revolution": {"t": time.time()}}
g2.candidates = [(1, 1376)]
s2.comeback.feed_line("Your party has been disbanded.")
s2.comeback.feed_line("You are no longer following Miserable.")
s2.comeback.tick()
check(f"party broke during the trip: no @comeback ({sent})", not any("@comeback" in c for c in sent))
hold = T2.hold
T2.hold = None
s2.bot.x._followed = "Miserable"
s2.comeback.feed_line("You are no longer following Miserable.")
check(f"(without the trip it would have: {sent[-1:]} = locate, then @comeback)",
      any("@comeback" in c for c in sent) or getattr(s2.comeback, "_comeback_ask", None))
s2.comeback._comeback_ask = None
T2.hold = hold
sent.clear()
s2.bot.x._following = "Miserable"
g2.candidates = [(1, 300)]
T2.party_msg("Miserable", "train 6 1/1376")
check(f"not in the trainer's room: refuses ({sent[-1]})", sent[-1] == "/Miserable @ptrain done 0 notthere")
g2.candidates = [(1, 1376)]
T2.party_msg("Miserable", "train 6 1/1376")
check("in the room: trains on the order (no walking)", T2.me is not None and T2.member_job)
res_me = T2.me
T2.me["phase"] = "after"; T2.me["trained"] = 1; T2.me["why"] = "all banked levels trained"
T2.tick()
T2.tick()
check(f"done → tells the leader ({sent[-1]})", sent[-1].startswith("/Miserable @ptrain done 1"))
T2.party_msg("Miserable", "trip off")
check("'trip off': hold over", not T2.holding_comeback())
check("member never starts a trip at a lap end", T2.lap_end(mp) is False)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
