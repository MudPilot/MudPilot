"""0.8.224: bugs found in the six characters' real logs (2026-11-21 log mining)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView, MOVE_FAIL_RE
from mudpilot.automation import Automation
from mudpilot.messagerules import MessageRules
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.char_level = 55; st.my_name = "Leader"
st.party_comeback = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True


class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass


sent = []
s.telnet = T(); s._entered = True
logs = []
s.log = lambda m, *a, **k: logs.append(str(m))
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


# 1: the stall watchdog counts the game's own spell lines as our attack
for line in ("Your flaming magma blast strikes the cave troll for 97 damage!",
             "A storm of raw energy blasts your foes for 314 damage!", "You raise your hands in the air!"):
    check(f"our attack: {line}", Automation.OWN_ATTACK_RE.match(line))
for line in ("The cave troll hits you for 20 damage!", "Your healing touch heals you for 20 damage!"):
    check(f"not ours: {line}", not Automation.OWN_ATTACK_RE.match(line))

# 2: a member who drops isn't "back" because the room display from before the disconnect still lists them
cb = s.comeback
s.state.party = {"Leader": {"t": time.time() - 30}, "Evolution": {"t": time.time() - 30}}
s.bot.x._own_party = True
s.state.view = RoomView("Bristlewood Grove", {"N"}, [], [], ["Evolution"], time.time() - 5)
time.sleep(0.01)
cb.feed_line("Evolution just disconnected!!!")
had = "Evolution" in cb.missing
cb._prune_back()
check(f"dropped member still missing after the prune (noted {had}): {dict(cb.missing)}",
      had and "Evolution" in cb.missing)
time.sleep(0.01)
s.state.view = RoomView("Bristlewood Grove", {"N"}, [], [], ["Evolution"], time.time())
cb._prune_back()
check("…and back once a new room display shows them", "Evolution" not in cb.missing)

# 3: "You are engulfed!" is a refused move (held), not a wall
check("engulfed: a failed move", MOVE_FAIL_RE.search("You are engulfed!"))
check("engulfed: confirms being held", MessageRules.HELD_CONFIRM_RE.search("You are engulfed!"))

# 4: joining someone: disband our own party with 'disband party' (a bare 'disband' is this board's gang command)
src = open(os.path.join(here, "mudpilot", "session.py"), encoding="utf-8").read()
check("session sends 'disband party', not a bare 'disband'",
      'self.send("disband party"' in src and 'self.send("disband",' not in src)

# 5: "Reset session stats" mid-lap keeps the lap's progress
ls = s.loopstats
g = s.state
g.exp_gained, g.kills = 150000, 20
s.stats.rests = 2
ls._lap = {"key": "k", "title": "t", "t": time.time() - 300, "exp": 100000, "kills": 12, "rests": 1, "deaths": 0,
           "lairs_full": 0, "lairs_empty": 0, "seen": set()}
g.reset_stats()
g.exp_gained += 30000; g.kills += 3
done_exp, done_k = g.exp_gained - ls._lap["exp"], g.kills - ls._lap["kills"]
check(f"lap progress kept over a stats reset: {done_exp} exp, {done_k} kills (50000+30000, 8+3)",
      done_exp == 80000 and done_k == 11)

# logPVE 1: leaving a No-attack room — while the move is on its way, it's still the No-attack room
from mudpilot.automation import path_from_route
from mudpilot.megamud_files import STEPF
w, b = s.world, s.bot
r = w.route((1, 1), (1, 5), level=55) or w.route((1, 1), (1, 2), level=55)
mp = path_from_route(w, (1, 1), r, name="t")
if len(mp.steps) >= 2:
    mp.steps[0].flags |= STEPF["NOATTACK"]
    b.path, b.walking, b.idx = mp, True, 0
    g.candidates = [(1, 1)]
    g.view = RoomView("x", {"N"}, ["orc"], [], [], time.time())
    before = b._step_flag("NOATTACK")
    time.sleep(0.01)
    b._step_sent_at = time.time()
    g.pending.append(("move", mp.steps[0].move, (1, 1)))
    b.idx = 1
    during = b._step_flag("NOATTACK")
    g.pending.clear()
    time.sleep(0.01)
    g.view = RoomView("y", {"S"}, [], [], [], time.time())
    after = b._step_flag("NOATTACK")
    check(f"No-attack room: before the move {before}, move on its way {during}, arrived {after}",
          before and during and not after)
    b.walking, b.path = False, None
check("our attack: You move your hands in a mystical pattern!",
      Automation.OWN_ATTACK_RE.match("You move your hands in a mystical pattern!"))

# logPVE 2: after Combat Off's refresh, nothing is done until the room shows again (2.5 s at most)
src = open(os.path.join(here, "mudpilot", "automation.py"), encoding="utf-8").read()
check("tick waits for the refreshed room after a kill", "self._refresh_at = now" in src and
      "now - ra < 2.5" in src)

# logREV 1: still knocked down: no "@ok — ready to go" to the leader yet
x = s.bot.x
x._sent_wait, x._wait_to = True, "Revolution"
x.cfg.party_resume_msg = "@ok"
x.care._reported = {"knocked"}; x.ailments["knocked"] = time.time()   # (0.8.224.2: the live condition counts)
sent.clear()
x.release_hold("held")
check(f"down: no @ok yet ({sent})", not any("@ok" in c for c in sent) and x._sent_wait)
x.care._reported = set(); x.ailments.pop("knocked", None)
x.release_hold("held")
check(f"up again: @ok sent ({sent})", any("@ok" in c for c in sent) and not x._sent_wait)

# logREV 2: 'no effect' after two blesses at once blames the one that isn't our spell (or none)
b._buff_cast = {"flux": time.time() - 0.2, "ntap": time.time() - 0.1}
b._buff_noeffect = {}
b._my_spell_shorts = lambda: {"ntap"}
for _ in range(3):
    b.note_line("Your command had no effect.") if hasattr(b, "note_line") else None
nx = getattr(b, "_buff_noeffect", {})
check(f"'no effect' with flux + ntap sent: flux blamed, not ntap ({nx})", "ntap" not in nx and "flux" in nx)
del b._my_spell_shorts

# logREV 3 / 4
check("area spell not re-sent before *Combat Engaged*",
      "time.time() - (getattr(self, \"_area_armed\", 0) or 0) < 3.5" in src)
for line in ("You glow a brilliant white and point a finger at fierce copsewight!",
             "You summon a powerful tempest into the room!", "Your foes are drenched in acid for 172 damage!",
             "You raise your palm towards the orc!"):
    check(f"our attack: {line}", Automation.OWN_ATTACK_RE.match(line))
check("not ours: Your defenses are vulnerable!", not Automation.OWN_ATTACK_RE.match("Your defenses are vulnerable!"))

# --- regression walks (0.8.223 vs 0.8.222) ---
# W1: the stretch wall took every raftable river out of the 'every item' plan — the raft errand is back
saved_char = dict(w.char or {})
def plan_(a, z, hp, have):
    w.char = dict(saved_char, max_hp=hp, hangup_pct=30, carried=frozenset(), gate_any=False)
    w.forget_routes(); w.stretch_blocks = {}
    return w.route(a, z, level=30, have=have)
check("boat items are the shop-sold ones (log raft in, no phoenix feather)",
      any(w.item_name(i) == "log raft" for i in w._boat_items()) and
      not any("phoenix" in w.item_name(i) for i in w._boat_items()))
for a, z in [((14, 2350), (14, 10066)), ((14, 4860), (14, 3297)), ((1, 98), (1, 2396))]:
    r = plan_(a, z, 390, set(w.items))
    check(f"planning with every item, {a} -> {z} crosses the river with a raft ({len(r or [])} steps)", r)
r = plan_((7, 995), (15, 1137), 533, set(w.items))
check("0.8.224.2 (Dan): the Lava Tube at 533 HP is walked — rooms that hurt never refuse", r is not None)
# w1214 #3: one last search round every room that hurts before saying no route
r = plan_((14, 1923), (14, 9045), 520, set())   # (0.8.224: limit = hang-up line; its way has a 350 trap)
check(f"14/1923 -> 14/9045 at 520 HP: the dry way ({len(r or [])} steps)", r and
      sum(w.room_damage(e.to, ()) for e in r) == 0)
w.char = saved_char; w.forget_routes()
# W2: an errand leg's party @have round still asks the party's quest flags
esrc = open(os.path.join(here, "mudpilot", "errands.py"), encoding="utf-8").read()
check("errand leg: party quest-flag check before start_path", "bot.partyflags.check(mp, loop)" in esrc)

# logEVO A: the low-HP hang-up re-arms 3% over the line, not the moment HP touches it
sf = s.safety if hasattr(s, "safety") else None
if sf is not None and hasattr(sf, "_low_hp_check"):
    s.telnet.connected = True; s._entered = True
    g.last_prompt = time.time(); s._connected_at = time.time() - 60
    sf.cfg.hangup_low_hp, sf.cfg.hangup_hp_pct = True, 25
    hung = []
    sf.hangup = lambda why: hung.append(why)
    sf._was_in, sf._hp_armed, sf._hp_floor = True, False, 17.0
    g.max_hp = 710
    for hp in (184, 174):              # 25.9% (mend), then 24.5% (our own ring swap)
        g.hp = hp; sf._low_hp_check()
    check(f"25.9% then 24.5% after coming back in low: no hang-up ({hung})", not hung)
    for hp in (200, 170):              # 28.2% re-arms, then a real dip
        g.hp = hp; sf._low_hp_check()
    check(f"…28% re-arms, a dip to 24% hangs up ({hung})", len(hung) == 1)
else:
    check("safety module found", False)

# logEVO E: a text exit that failed takes its other wordings to the same room with it
asrc = open(os.path.join(here, "mudpilot", "automation.py"), encoding="utf-8").read()
check("route_around fails every text exit to the same room", "e2.kind == \"text\" and tuple(e2.to) == tuple(ex_.to)" in asrc)

# w1617 #2: inside a key door typed as a plain locked door, without its key: the key is a hard need
out = w.rooms[(16, 2118)].exits.get("E") if (16, 2118) in w.rooms else None
if out is not None and w.key_twin(out) is not None:
    jk = w.exit_need(w.key_twin(out))[0]
    w.char = dict(saved_char, door_power=(0, 40))
    tn = b._twin_need(out, set())
    check(f"Fiery Lair way out without the key, strength 40: the key's a hard need ({tn})", tn and tn[0] == jk and not tn[1])
    check("…and no need with the key in hand", b._twin_need(out, {jk}) is None)
    w.char = saved_char
# w1617 #3: the bank-trip check skips when no toll over your cash leads towards the target
check("leads_to: the map-only set of rooms leading to a target", (1, 1) in w.leads_to((1, 2)) or len(w.leads_to((1, 2))) > 10)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
