"""0.8.224: Dan's answers to the 2026-11-22 bug hunt list (HUNT_1122.md)."""
import os, sys, time, tempfile
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.automation import Automation
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.char_level = 60; st.my_name = "Tester"
st.hangup_low_hp = True; st.hangup_hp_pct = 30
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True


class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False


sent, logs = [], []
s.telnet = T(); s._entered = True
s.log = lambda m, *a, **k: logs.append(str(m))
ok = True


def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


w, b, g = s.world, s.bot, s.state
src = open(os.path.join(here, "mudpilot", "automation.py"), encoding="utf-8").read()

# 2: the limit is the hang-up line
saved_char = dict(w.char or {})
w.char = dict(saved_char, max_hp=500, hangup_pct=30, carried=frozenset(), gate_any=False)
check(f"stretch limit: 500 HP, 30% hang-up -> 350 ({w.stretch_limit()})", w.stretch_limit() == 350)
w.char = dict(w.char, hangup_pct=0)
check("…no hang-up set: the whole max HP", w.stretch_limit() == 500)
w.char = dict(w.char, hangup_pct=30)

# 1 + 5: refused, quick to refuse again, and walked once you said yes
w.forget_routes(); w.stretch_blocks = {}; w.stretch_ok = {}
r = w.route((1, 2), (6, 472), level=60, have=set())
check("Misty Bog at 500 HP: refused without a yes", r is None and ((1, 2), (6, 472)) in w.stretch_blocks)
t0 = time.time()
r2 = w.route((1, 2), (6, 472), level=60, have=set(), avoid=frozenset({(1, 99999)}))
check(f"…the same refusal again (another avoid set) comes back at once ({time.time() - t0:.2f} s)",
      r2 is None and time.time() - t0 < 1.0)
w.stretch_ok = {(6, 472): time.time()}; w.forget_routes()
r3 = w.route((1, 2), (6, 472), level=60, have=set())
check(f"…said yes: walked ({len(r3 or [])} steps)", r3)
w.stretch_ok = {}; w.forget_routes()
check("the app asks 'Go anyway?' for kind 'hurt'",
      'kind == "hurt"' in open(os.path.join(here, "mudpilot", "app.py"), encoding="utf-8").read())

# 3: a shop-sold counter is offered
g.max_hp = 500; g.hp = 500; g.level = 60
b.held_items = lambda: set()
cn = b._stretch_counter(([(6, 472), (6, 466)], 820))
check(f"Misty Bog: the counter offered is a shop item ({cn and cn[2]})", cn and "boots" in cn[2].lower())
asked = []
w.char = dict(w.char, max_hp_who=None)
okc = b._ask_counter((6, 472), ([(6, 472)], 820), cn, lambda *a: asked.append(a) or True) if cn else False
check("…yes: it counts as carried for that Go to", okc and w.stretch_counter.get((6, 472)) == cn[0])
w.stretch_counter = {}; b._counter_buy = None
w.char = saved_char; w.forget_routes()

# 4: no avoided-area / quest-flag detours when rooms that hurt are the block
check("avoid message skipped on a hurt block", "if route is None and ab and not hurt_block" in src)
check("no 'abil' re-read on a hurt block", "and not hurt_block and self._ask_gate_abilities" in src)
check("look-alike behind rooms that hurt is named", "the look-alike room" in src)

# 6: a timed door is gone round at most every 10 s
check("timed door: TIMED_ROUND_SECS guard", Automation.TIMED_ROUND_SECS >= 5 and "_timed_round_at" in src)

# 7: the dropper estimate uses what you really do a round
d = s.danger
mon = next(m for m in (getattr(w, "monsters", None) or {}).values() if (m or {}).get("hp")) \
    if getattr(w, "monsters", None) else {"num": 1, "hp": 1000}
s.spell_candidates = lambda: []
base = d.my_dpr(dict(mon, num=-5))
s.combatlog.my_rounds, s.combatlog.my_round_avg = 30, 320.0
seen = d.my_dpr(dict(mon, num=-6))
check(f"melee, nothing seen: a level guess, not 60 ({base:.0f})", base >= 250)
check(f"…with 30 rounds seen at ~320: that ({seen:.0f})", abs(seen - 320) < 1)

# 8: low-HP hang-up in a party: back in after a minute, twice at most; never after PvP
sf = s.safety
s.state.party = {"Tester": {"t": time.time()}, "Evolution": {"t": time.time()}}
s.remember_party = lambda: None
b.stop = lambda *a, **k: None
s.show_down = lambda *a, **k: None
sf._party_relog = None
sf.hangup("HP 100/710 below 30%")
check(f"party low-HP hang-up: back in {sf.PARTY_RELOG_SECS} s, not held at the menu",
      sf._party_relog and sf._party_relog["n"] == 1 and not s.hold_realm and s._want_connected
      and 50 < sf.hung_up_until - time.time() <= 61)
# back in: monsters still there -> out again (try 2)
s.telnet.connected = True
g.view = RoomView("Stonecaps", {"N"}, [("stonecap", None)], [], [], time.time())
sf.on_room(g)
check("…back in with a monster still there: straight back out (try 2)", sf._party_relog and sf._party_relog["n"] == 2)
s.telnet.connected = True
sf._party_relog["looked"] = False
sf.on_room(g)
check("…a third time: offline for good", sf._party_relog is None and s.hold_realm and not s._want_connected)
s.hold_realm = False; s._want_connected = True; s.telnet.connected = True
sf._party_relog = {"n": 1, "t": time.time(), "looked": False}
g.view = RoomView("Stonecaps", {"N"}, [], [], [], time.time())
sf.on_room(g)
check("…back in to a clear room: stays", sf._party_relog is None and s.telnet.connected)
sf.hangup("PvP: Bob attacked you")
check("PvP hang-up: never back in by itself", s.hold_realm and not s._want_connected and sf.hung_up_until == float("inf"))
s.hold_realm = False; s._want_connected = True; sf.hung_up_until = 0; s.telnet.connected = True
s.state.party = {}

# 9: a heal far smaller than the damage coming in is skipped
g.max_hp, g.hp = 600, 300
b._heal_seen = {"minor healing": [8, 13, 13]}
b._cmd_spell = lambda c, w_: {"Name": "Minor Healing"} if (c or "").startswith("mihe") else None
s.combatlog.rounds.clear()
s.combatlog.rounds.append({"t": time.time(), "last": time.time(), "done": 0, "taken": 320})
check("mihe heals ~11 while taking 320 a round: skipped", b._heal_too_small("mihe"))
s.combatlog.rounds.clear()
s.combatlog.rounds.append({"t": time.time(), "last": time.time(), "done": 0, "taken": 30})
check("…taking 30 a round: heals", not b._heal_too_small("mihe"))
check("heal line read", Automation.HEALED_RE.match("you cast minor healing on tester, healing 8 damage!"))
del b._cmd_spell

# 10: held / engulfed with Combat off: fight back
b.x.ailments = {"held": time.time()}
check("held now", b._held_now())
b.x.ailments = {"held": time.time() - 120}
check("…a minute later without a 'free' line: not any more", not b._held_now())
from mudpilot.extras import STATUS_RES
check("'You are engulfed!' reads as held", STATUS_RES["held"][0].search("You are engulfed!"))
check("held fight in the tick", "held_fight = bool(not cfg.auto_combat and mobs and being_hit and self._held_now())" in src)
b.x.ailments = {}

# 11: waiting-on-the-party rests don't swap gear
swaps = []
real_bs = b._begin_swap
b._begin_swap = lambda k: swaps.append(k)
st.auto_rest = True; g.hp, g.max_hp = 300, 600; g.resting = False; g.in_combat = False
b._cool.clear(); b._no_rest_until = 0
b.idle_regen([], why="resting with Evolution (party sync)")
check(f"party-wait rest: no gear swap ({swaps})", not swaps)
b._begin_swap = real_bs

# 12: our own self-mend standing us up mid-rest keeps the regen gear on
b._swap, b._swap_rested, g.resting = "rest", True, False
b._last_spell_at = time.time()
b.walking = False
kept = b._swap_tick([], False) is False and b._swap == "rest"
check("self-mend mid-rest: regen gear stays on", kept)
b._last_spell_at = time.time() - 10
sent.clear(); b._swap_tick([], False)
check("…not our spell: the fighting gear goes back", b._swap is None)

# 13: no rest while hit with Combat off; a room that keeps breaking rests; unmatched loop
b._rest_broken = [(time.time(), (1, 2))] * 3
g.candidates = [(1, 2)]
check("3 broken rests here in 2 min: rest elsewhere", b._rest_broken_here())
b._rest_broken = []
check("being hit with Combat off: not resting", "Not resting: being hit with Combat off" in src)
check("unmatched MegaMUD loop: stops at once, says why", "that loop isn't matched to" in src)

# 14: forgotten ways are kept across sessions
tmp = tempfile.mkdtemp()
type(s).forgotten_file = property(lambda self: os.path.join(tmp, "forgotten_exits.json"))
w.forgotten = {((10, 179), "ne", (10, 180))}
s._forgotten_saved = 0
s._save_forgotten()
w.forgotten = set()
s._load_forgotten()
check("forgotten ways saved and loaded back", ((10, 179), "ne", (10, 180)) in w.forgotten)
check("…and not learned again", not w.add_learned((10, 179), "ne", (10, 180)))
w.forgotten = set()

# 16: a timer event logs once, then every 30 minutes
ev = {"name": "par", "when": "timer", "enabled": True}
logs.clear()
for _ in range(5):
    s.events._queue.clear()
    s.events.fire(ev, "timer")
check(f"timer event fired 5 times: logged once ({sum('fired' in l for l in logs)})",
      sum("fired" in l for l in logs) == 1)
s.events._queue.clear()

# 17: a disband you meant pauses invites AND joins for a few minutes; a late joiner is disbanded again
import mudpilot.session as sm
check(f"pause is a few minutes ({sm.PARTY_HOLD_SECS} s)", sm.PARTY_HOLD_SECS >= 180)
s._party_hold_until = 0
sent.clear()
s.send("invite Lyra", from_bot=True)
time.sleep(0.01)
s.send("disband party")
sent.clear()
s.send("join Evolution", from_bot=True)
check(f"no automatic join during the pause ({sent})", not any(c.startswith("join") for c in sent))
s.send("join Evolution")
check("…one you type still goes", "join Evolution" in sent)
sent.clear()
s._late_joiner("Lyra started to follow you.")
check(f"invite from before the disband accepted: disbanded again ({sent})", "disband party" in sent)
s._party_hold_until = 0

print("ALL PASS" if ok else "SOME FAILED")
