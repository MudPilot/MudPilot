"""0.8.29: loop analyzer, best spots, @where with room numbers, @ac from 'stat all'."""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st); b = s.bot; w = s.world
s._no_log_file = True
_tmp = tempfile.mkdtemp(); config.board_dir = lambda bd: os.path.join(_tmp, bd); s.lairclock._for = s.history._for = None
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
s.state.level = 30; s.state.max_hp = s.state.hp = 684; s.state.max_ma = s.state.ma = 473; s.state.ac, s.state.dr = 60, 10
# a start room with lairs nearby
from mudpilot.danger import lair_spawn
start = next(k for k, r in w.rooms.items() if k[0] == 1 and lair_spawn(w, k)[0] and any(m["exp"] > 0 for m in lair_spawn(w, k)[1]))
s.state.candidates = [start]
cands = s.loopbuilder.build(start, 40)
check("a loop to analyze", cands)
from mudpilot.megamud_files import path_from_route
mp = path_from_route(w, cands[0]["start"], cands[0]["route"], name="T")
a = s.analyzer.analyze(mp)
check(f"analysis: {a['lairs']} lairs, ~{a['exp_hr']/1000:.0f}k/hr", a["rows"] and a["lairs"] >= 1 and a["exp_hr"] > 0)
check("every lair row has a risk", all(r["risk"] for r in a["rows"] if r["lair"]))
check("MME-only ratings are marked '?'", all(r["risk"] in ("safe", "—") or r["risk"].endswith("?")
                                            for r in a["rows"] if r["lair"] and not r["observed"]))
check("tips given", a["tips"])
# observed fights replace MME's numbers
lr = next(r["room"] for r in a["rows"] if r["lair"] and r["need"] is not None)
for x in (40, 50, 45):
    s.danger.observe(lr, x)
a2 = s.analyzer.analyze(mp)
row = next(r for r in a2["rows"] if r["room"] == lr)
check(f"after real fights: no '?' ({row['risk']}, needs {row['need']:.0f}%)", row["observed"] and not row["risk"].endswith("?"))
# best spots
res = s.spots.find()
check(f"spots found ({len(res.get('spots', []))}, {res.get('reach')} rooms in reach)", res.get("spots"))
sp = res["spots"]
check("safe areas ranked before risky ones", [o["risk"].rstrip("?") for o in sp][:1] != ["deadly"])
check("each spot has a built loop", all(o["cand"]["route"] for o in sp))
# calibration from your own loops
key = s.bot.x.loop_key(mp); mp.filename = "/x/t.mp"; key = s.bot.x.loop_key(mp)
s.paths = [mp]
s.loopstats._loaded_for = st.board
s.loopstats.data = {key: {"title": "T", "by": {"miserable": [{"t": i, "secs": 300, "exp": int(a["exp_hr"] * 2 * 300 / 3600),
                                                              "kills": 5, "rests": 1, "deaths": 0, "level": 30,
                                                              "lairs_full": 1, "lairs_empty": 0} for i in range(5)]}}}
f, n = s.spots.calibration()
check(f"calibration ×{f:.2f} from {n} loop", n == 1 and 1.5 < f < 2.5)
# @where / @ac
st.remote_enabled = True; st.remote_channels = {"telepath": True}; st.remote_players = {"Dan": ["query", "location"]}
from mudpilot.gamestate import RoomView
s.state.view = RoomView(w.room(start).name, {"N", "S"}); s.state.view.t = time.time()
sent.clear(); s.remote.feed_line("Dan telepaths: @where")
check(f"@where gives map and room ({sent[-1] if sent else ''})", sent and f"map {start[0]} room {start[1]}" in sent[-1])
s.state.candidates = [start, (1, 2)]
sent.clear(); s.remote.feed_line("Dan telepaths: @where")
check(f"…and when unsure, the likely rooms ({sent[-1] if sent else ''})", sent and "not sure which" in sent[-1])
s.state.candidates = [start]
sent.clear(); s.remote.feed_line("Dan telepaths: @ac")
check(f"@ac types 'stat all' ({sent})", "stat all" in sent)
now = time.time()
s.timeline.screen.extend([(now, "Armour Class: 85/14"), (now, "AC vs Evil: 95/14   AC vs Good: 85/14"), (now, "Health: 60")])
s.remote._ac_waiting = [(w_[0], w_[1], now - 3) for w_ in s.remote._ac_waiting]
sent.clear(); s.remote.tick()
check(f"…and answers with the AC lines ({sent[-1] if sent else ''})", sent and "85/14" in sent[-1] and "Evil" in sent[-1] and "Health" not in sent[-1])
# 'pro' → room number in the conversation box; passwords never kept
s.chat.feed("Location:            1,1810")
e = s.chat.entries[-1]
check(f"pro → location line ({e[3]})", e[1] == "location" and "map 1 room 1810" in e[3])
s.timeline.line("Recover Password:    123456")
check("recover password never stored", "123456" not in s.timeline.screen[-1][1])
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
