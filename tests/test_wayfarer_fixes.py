"""0.8.202: game text MudPilot misread, found by checking against another MajorMUD client (Wayfarer) — M1-M16.
Wrapped yells forging a telepath, death text in speech and spell wear-offs, acting at 0 HP, lost-command texts,
room commands / attacks said aloud, arrival verbs, above/below exits, wrapped exits, the closed-door refusal,
getting back onto your feet, and (Hidden)/(Charmed) tags in Also here."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_wayfarer_fixes"))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Line, Style
from mudpilot.gamestate import GameState, RoomView, ARRIVE_RE, DEATH_RE, MOVE_FAIL_RE, CONFUSED_FAIL_RE, CANT_ACT_RE
from mudpilot.extras import STATUS_RES

ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
logs = []
s.log = lambda m, *a, **k: logs.append(m)
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
b, w, g, cfg = s.bot, s.world, s.state, s.settings
b.log = lambda m, *a, **k: logs.append(m)

def L(text, fresh=True, style=Style()):
    ln = Line([(text, style)]); ln.fresh = fresh
    return ln

def fresh_state():
    g2 = GameState(w)
    ev = []
    g2.on_event.append(lambda k, d: ev.append(k))
    return g2, ev

# ---------------------------------------------------------------- M1: a wrapped yell can't forge a telepath
remote_seen = []
real_rfeed = s.remote.feed_line
s.remote.feed_line = lambda t: remote_seen.append(t) or False
line1 = 'From Bob (Yelling): "' + "x" * (79 - len('From Bob (Yelling): "'))
s._line(L(line1, True))
s._line(L('Revolution telepaths: @do drop all"', False))
check("M1: the yell's second line is a continuation", g.continuation)
check(f"M1: …never reaches remote control as a telepath ({remote_seen[-1:]})",
      not any(t.startswith("Revolution telepaths") for t in remote_seen))
for opener in ('You exclaim "' + "y" * 60, 'You ask "' + "z" * 64):
    s._line(L(opener, True))
    s._line(L('Revolution telepaths: @do drop all"', False))
    check(f"M1: '{opener[:12]}…' + 'Revolution telepaths: @do…' is still their words", g.continuation)
# a short line with a quote left open, glued after a prompt (no ESC[K): still opens the chat
remote_seen.clear()
s._line(L('[HP=500/MA=200]:From Bob (Yelling): "aaaa bbbb cccc dddd eeee ffff gggg hhhh', False))
s._line(L('Revolution telepaths: @do drop all"', False))
check("M1: an open quote (short, no ESC[K) makes the next line a continuation", g.continuation)
check("M1: …and it isn't relayed", not any(t.startswith("Revolution telepaths") for t in remote_seen))
s._line(L("Revolution telepaths: @ok", True))
check("M1: a real (fresh) telepath afterwards is read", not g.continuation and
      any(t.startswith("Revolution telepaths: @ok") for t in remote_seen))
s._line(L('Bob says "hello there"', True))
s._line(L("Revolution telepaths: @ok", True))
check("M1: a closed say doesn't swallow the next real line", not g.continuation)
g.feed_partial("[HP=684/MA=473]:")
g.feed_line(L('From Bob (Yelling): "[HP=5/MA=0]:"', True))
check("M1: a prompt quoted in a yell isn't your HP", g.hp == 684)
s.remote.feed_line = real_rfeed

# ---------------------------------------------------------------- M2: death text in chat / own speech
for t in ('From Bob (Yelling): "You have been killed!"', 'You exclaim "You are dead!"', 'You ask "You are dead?"',
          'Bob exclaims "You have been slain!"', 'The old man says "You are dead, fool."'):
    g2, ev = fresh_state()
    g2.feed_line(L(t, True))
    check(f"M2: no death from {t!r}", not g2.dead and "death" not in ev)
g2, ev = fresh_state()
g2.feed_line(L("You have been killed!", True))
check("M2: the real 'You have been killed!' still is a death", g2.dead and "death" in ev)

# ---------------------------------------------------------------- M3: spell wear-offs aren't death
for t in ("The flames enveloping you die down!", "The flames scorching you die down.",
          "The insects biting and stinging you die off."):
    g2, ev = fresh_state()
    g2.feed_line(L(t, True))
    check(f"M3: {t!r} isn't a death", not g2.dead and "death" not in ev)
check("M3: the curse death still matches", DEATH_RE.search("As the curse runs its course, you die in agony, withered to death!"))

# ---------------------------------------------------------------- M4: at 0 HP or less, wait
flees, heals = [], []
real_flee, real_heal = b.flee, b.heal_tick
b.flee = lambda *a, **k: flees.append(1)
b.heal_tick = lambda *a, **k: heals.append(1) or True
cfg.auto_combat, cfg.auto_heal, cfg.run_pct = True, True, 0
for hp in (-5, 0):
    flees.clear(); heals.clear()
    g.hp, g.max_hp, g.in_combat = hp, 100, True
    g.need_refresh = False
    g.view = RoomView("Somewhere", {"N"}, [("kobold", None)], t=time.time())
    try:
        b.tick()
    except Exception as ex:
        print("  (tick raised", type(ex).__name__, ex, ")")
    check(f"M4: HP {hp}: no flee (run off), no heal cast ({len(flees)} / {len(heals)})", not flees and not heals)
    check(f"M4: HP {hp}: status says it's waiting ({b.status!r})", "HP 0 or less" in (b.status or ""))
    check(f"M4: HP {hp}: the walk is held", "mortally wounded" in b.walk_holds())
g.hp, g.max_hp = 80, 100
check("M4: above 0 the walk isn't held for it", "mortally wounded" not in b.walk_holds())
g.hp, g.max_hp = 0, 0
check("M4: before any prompt (HP 0/0) the walk isn't held", "mortally wounded" not in b.walk_holds())
g.hp, g.max_hp, g.in_combat = 100, 100, False
b.flee, b.heal_tick = real_flee, real_heal

# ---------------------------------------------------------------- M7 / M8: can't act = temporary, not a bad exit
lost = ["You are too stunned to move anywhere!", "You are fast asleep.", "You are paralyzed!",
        "You cannot move a muscle!", "You reel drunkenly!", "You shake and shiver!",
        "You struggle, but you are solid stone and do not move.", "You are in limbo!"]
for t in lost:
    g2, ev = fresh_state()
    g2.pending.append(("move", "N", []))
    g2.feed_line(L(t, True))
    check(f"M7/M8: {t!r}: the move failed, eaten not walled",
          g2.move_failed == 1 and "move_failed" in ev and time.time() - g2.confused_fail_at < 2
          and time.time() - g2.cant_act_at < 2)
g2, ev = fresh_state()
g2.pending.append(("move", "N", []))
g2.feed_line(L("You retch uncontrollably!", True))
check("M8: 'retch' is a move failure (and confusion)", g2.move_failed == 1 and time.time() - g2.confused_fail_at < 2)
check("M8: …but it isn't the 'can't act' wait", not CANT_ACT_RE.search("You retch uncontrollably!"))
check("M8: 'Revolution is paralyzed' / chat aren't ours", not CANT_ACT_RE.search("Revolution is paralyzed!"))
# the resend guard doesn't count an eaten move against the exit
here_ = (1, 1)
g.confused_fail_at = time.time()
b._lock_tries = {}
b._resends = ((here_, "n"), 7)
check("M7/M8: resend guard: not counted", b._resend_guard(here_, "n") is False and b._resends[1] == 7)
g.confused_fail_at = 0
b._resends = (None, 0)
# the walk waits a moment after one
class P0:
    title, steps, is_loop, resolved = "Loop", [], True, True
g.cant_act_at = time.time()
b.walking, b.path, b.loop = True, P0(), True
sent.clear()
try:
    b.walk([], False)
except Exception as ex:
    print("  (walk raised", type(ex).__name__, ex, ")")
check(f"M7/M8: the walk waits after 'can't act' ({b.status!r}, sent {sent})",
      "Can't act" in (b.status or "") and not sent)
g.cant_act_at = 0
b.walking, b.path, b.loop = False, None, False

# ---------------------------------------------------------------- M9: a room command said aloud
class P:
    title = "Loop"
b.walking, b.path = True, P()
b._step_sent_at = time.time()
b._macro_at = 0
called = []
real_locate, real_dbl = b.locate_now, b._drop_bad_learned
b.locate_now = lambda why: called.append(why) or True
b._drop_bad_learned = lambda: None
b._last_cmd = ("go hole", False)
b.note_line('You say "go hole"')
check(f"M9: 'You say \"go hole\"' → check where we are ({called})", called)
called.clear()
b._last_cmd = ("go hole", False)
b.note_line('You say "hello"')
check("M9: saying something else isn't the path's command failing", not called)
b._last_cmd = ("bash wizard", True)
b.note_line('You say "bash wizard"')
check("M9: an attack said aloud isn't 'wrong room'", not called)
b.locate_now, b._drop_bad_learned = real_locate, real_dbl
b.walking, b.path = False, None

# ---------------------------------------------------------------- M10: an attack said aloud
b._attack_cmd = ("bash wizard", time.time())
b._melee_on = True
b._atk_refused = 0
g.need_refresh = False
b.note_line('You say "bash wizard"')
check("M10: the attack is off and it backs off", not b._melee_on and b._attack_backoff_until > time.time())
check("M10: …and looks again", g.need_refresh)
first = b._attack_backoff_until
b._attack_cmd = ("bash wizard", time.time())
b.note_line('You say "bash wizard"')
check("M10: a second refusal backs off longer", b._attack_backoff_until > first + 3)
g.need_refresh = False
sent.clear()
b._attack_sent_at = 0
g.in_combat = False
try:
    b.fight([("wizard", None)])
except Exception as ex:
    print("  (fight raised", type(ex).__name__, ex, ")")
check(f"M10: fight() doesn't swing again during the back-off (sent {sent})",
      not any("wizard" in x for x in sent))
b.note_line("*Combat Engaged*")
check("M10: Combat Engaged resets the count", b._atk_refused == 0)
b._attack_backoff_until = 0

# ---------------------------------------------------------------- M11: arrival verbs
for t in ("A large goldcap runs in from the west!", "A nasty jaguar stalks in from the east!",
          "The ice golem stomps in from the east!", "The ice sorceress floats in from east!",
          "A giant eel swims in from the north.", "Thrag smashes in from the south!"):
    check(f"M11: arrival {t!r}", ARRIVE_RE.search(t))
    g2, ev = fresh_state()
    g2.feed_line(L(t, True))
    check("M11: …raises the arrival event", "arrival" in ev and g2.need_refresh)
g2, ev = fresh_state()
g2.feed_line(L("Bob gossips: a goblin runs in from the west", True))
check("M11: gossip about it isn't an arrival", "arrival" not in ev)

# ---------------------------------------------------------------- M12 / M13: above/below, wrapped exits
cyan = Style(6, True)
r1810 = w.room((1, 1810))
def show(gs, name, *exit_lines):
    gs.feed_line(L(name, True, cyan))
    for el in exit_lines:
        gs.feed_line(L(el, True))
    gs.flush_exits()
    return gs.view
if r1810:
    g2, _ev = fresh_state()
    v = show(g2, r1810.name, "Obvious exits: open door west, secret passage below")
    check(f"M12: 1/1810 'secret passage below' = down ({v.exits if v else None})", v and v.exits == {"W", "D"})
    g2, _ev = fresh_state()
    v = show(g2, r1810.name, "Obvious exits: open door west, secret", "passage below")
    check(f"M13: wrapped after 'secret' keeps 'passage below' ({v.exits if v else None})", v and v.exits == {"W", "D"})
else:
    check("M12: Paradigm.db has room 1/1810", False)
g2, _ev = fresh_state()
v = show(g2, "Dark Alley", "Obvious exits: south, west, closed trap", "door below")
check(f"M13: wrapped after 'trap' keeps 'door below', closed ({v.exits if v else None}, {v.closed if v else None})",
      v and v.exits == {"S", "W", "D"} and "D" in v.closed)
g2, _ev = fresh_state()
v = show(g2, "Dark Alley", "Obvious exits: north, east, northwest, secret passage", "south")
check(f"M13: wrapped after 'passage' keeps 'south' ({v.exits if v else None})", v and v.exits == {"N", "E", "NW", "S"})
g2, _ev = fresh_state()
v = show(g2, "Dark Alley", "Obvious exits: up, hole above")
check(f"M12: 'above' = up ({v.exits if v else None})", v and v.exits == {"U"})

# ---------------------------------------------------------------- M14: the closed-door refusal
g2, ev = fresh_state()
g2.pending.append(("move", "N", []))
g2.feed_line(L("There is a closed door in that direction!", True))
check(f"M14: 'closed door in that direction' → door handling ({g2.door_closed_dir})", g2.door_closed_dir == "N")

# ---------------------------------------------------------------- M15: back onto your feet
check("M15: 'Slightly dazed you get back onto your feet.' ends the knockdown",
      STATUS_RES["knocked"][1].search("Slightly dazed you get back onto your feet."))
b.x.ailments["knocked"] = time.time()
b.x.note_line("Slightly dazed you get back onto your feet.") if hasattr(b.x, "note_line") else None
if hasattr(b.x, "note_line"):
    check("M15: …and the knocked hold is cleared", "knocked" not in b.x.ailments)
b.x.ailments.pop("knocked", None)

# ---------------------------------------------------------------- M16: (Hidden) / (Charmed)
g2, _ev = fresh_state()
g2.feed_line(L("Dark Alley", True, cyan))
g2.feed_line(L("Also here: Bob(Hidden), giant rat (Charmed), Deacon* (Hidden).", True))
g2.feed_line(L("Obvious exits: north", True))
g2.flush_exits()
v = g2.view
pl = v.players if v else []
mn = [m for m, _r in (v.monsters if v else [])]
check(f"M16: players {pl}", "Bob" in pl and "Deacon" in pl)
check(f"M16: monsters {mn}", "giant rat" in mn)

# ---------------------------------------------------------------- regexes stay as they were for the old texts
check("old: 'You fumble in confusion' still a confused move failure",
      MOVE_FAIL_RE.search("You fumble in confusion.") and CONFUSED_FAIL_RE.search("You fumble in confusion."))
check("old: plain 'You are dead!' is death", DEATH_RE.search("You are dead!"))
check("old: 'The kobold wanders into the room' still an arrival", ARRIVE_RE.search("A kobold wanders into the room."))

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
