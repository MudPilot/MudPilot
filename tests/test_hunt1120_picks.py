"""0.8.222 (Dan's picks from the 2026-11-20 bug hunt, bug_hunt/HUNT_1120.md "For Dan"):
1. Go to doesn't walk into a pocket whose only ways out are doors nobody can open (Stone Barracks 14/6217).
2. The only way is a '1000' door nobody opens: stop before setting off (not Morukai's lair door — that one opens).
3. A trap or room that can do your whole max HP is never planned (8/1835's 200-damage trap at 156 HP).
5. A locked door on the way and picklocks / strength not read: 'st' first.
6. A toll / fare your cash won't cover: off to the bank first.
8. A way in that needs a particular monster there: says so, doesn't go to a look-alike.
9. A scattered member: the walk waits for their @where answer, 30 s at most.
10. @stop'd but still following after ~2 minutes: the held @rego goes ahead (logged)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.char_level = 40; st.my_name = "Miserable"
st.auto_get_items = False; st.bash_key_doors = False
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.state.inv_at = float("inf")
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True; s.state.level = 40
s.on_no_route = lambda m: None
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
w, b, g = s.world, s.bot, s.state

def at(room, carrying="", pick=10, strength=30, level=40, wealth=None):
    b.stop("Stopped by you"); b.errands.cancel()
    s.trips.reset("test")
    b._pending_abil = None
    g.candidates = [room]; g.level = level; st.char_level = level
    g.carrying = carrying; g.keys = ""; g.inv_seq += 1
    g.picklocks, g.strength = pick, strength
    g.wealth = wealth
    w.forget_routes(); w.refused_doors = {}
    b._cool.pop("goto_st", None)

# 1. Stone Barracks: in by the key door (key in hand). 0.8.223 (Dan, regr222 #3): its other side, typed
#    '(Door [80 picklocks/strength])' (14/6217 E), is the same door — the key opens it, so this walks now
key = w.item_name(3702)
at((14, 6159), carrying=key)
r = b.goto((14, 6220))
check(f"Stone Barracks with the key, strength 30: goes — the way out is the key door's other side ({r}; "
      f"{b.no_route_msg[:90]})", r and b.walking)
check("…14/6217 E is that key door's other side", w.key_twin(w.rooms[(14, 6217)].exits["E"]) is not None)
at((14, 6159), carrying=key, strength=100)
r = b.goto((14, 6220))
check(f"…strength 100 bashes the way out: goes ({r}, walking {b.walking})", r and b.walking)

# 2. a '1000' door nobody opens as the only way: stopped up front; Morukai's lair door isn't one of those
at((15, 731))
ex = w.rooms[(15, 731)].exits["NE"]
r = b._goto_check((15, 731), (15, 410), [ex], None, None)
check(f"'1000' door the only way: not going ({r}; {b.no_route_msg[:80]})",
      r is False and "nobody at any level" in b.no_route_msg)
at((9, 1423))
ex = w.rooms[(9, 1423)].exits["W"]
check("Morukai's lair door (9/1423 W) isn't a stuck door", not w.stuck_door(ex))

# 3. traps / rooms that can do your whole max HP
trap = w.rooms[(8, 1835)].exits["S"]                 # (Trap, 200 damage)
w.char = dict(w.char or {}, max_hp=156)
check(f"156 HP: the 200-damage trap is a wall ({w.hp_wall(trap)})", w.hp_wall(trap) == 200 and not w.can_use(trap))
w.char = dict(w.char, max_hp=250)
check("250 HP: it isn't", w.hp_wall(trap) == 0)
w.char = dict(w.char, max_hp=156)
bl = w.why_no_route((8, 1835), (8, 1831), level=12, have=set())
check(f"why_no_route says so ({bl[:1]})", not bl or any("whole max HP" in why for _r, _d, why in bl))

# 5. a locked door on the way and stats not read: 'st' first
at((14, 6233), carrying="astral staff", pick=0, strength=0)   # Dirt Alley: in by '[80 picklocks/strength]'
sent.clear()
r = b.goto((14, 6230))
check(f"stats not read: 'st' first ({r}, {sent})", r is True and "st" in sent and not b.walking)
check("…and the Go to waits for it", b._pending_abil and tuple(b._pending_abil[0]) == (14, 6230))
at((14, 6159), carrying=key, pick=0, strength=0)
sent.clear()
r = b.goto((14, 6220))
check(f"…Stone Barracks with the key: no 'st' — the key opens the way back out ({sent})", "st" not in sent)
at((14, 6233), carrying="astral staff", pick=0, strength=0)
sent.clear()
r = b.goto((14, 6234))
check(f"…not when nothing on the way or out needs them ({sent}, walking {b.walking})", "st" not in sent and b.walking)

# 6. 0 copper on you and a fare in the way: the bank first
at((14, 1), carrying="astral staff", wealth=0, level=55, strength=100)
r = b.goto((13, 503))
t = s.trips.trip
check(f"0 copper, a 2,000,000 fare: off to the bank ({r}, {t and t.get('kind')}, {b.no_route_msg[:80]})",
      r and t is not None and t.get("kind") == "withdraw" and t.get("goto") == (13, 503))
s.trips.reset("test")
at((14, 1), carrying="astral staff", wealth=0, level=55)          # strength 30: the 61 door at 14/332 is no way back
r = b.goto((13, 503))
check(f"…strength 30: refused before any bank run, not after the withdraw (flags2 #2) ({r}, {s.trips.trip})",
      r is False and s.trips.trip is None and "no way back out" in b.no_route_msg)
s.trips.reset("test")

# 8. a way in that needs a monster there
at((14, 1290), level=60)
r = b.goto((14, 10450))
check(f"Castle Courtyard: 'needs … there', no look-alike ({r}; {b.no_route_msg[:110]})",
      r is False and "there" in b.no_route_msg and "needs" in b.no_route_msg and not b.walking)

# 9. a scattered member: hold the walk for their @where answer, 30 s at most
cb = s.comeback
st.party_comeback = True
cb.fetch = {"name": "Revolution", "phase": "asked", "no_invite": True, "t": time.time(), "back": None, "room": None}
check(f"scattered, asked @where just now: walk held ({cb.holding()})", cb.holding() == "Revolution")
cb.fetch["t"] = time.time() - 31
check("…not after 30 s", cb.holding() is None)
cb.fetch = None

# 10. @stop'd but never logged off: the held @rego goes ahead after ~2 minutes
regos = []
b.rego = lambda *a, **k: regos.append(1) or True
now = time.time()
g.party = {"Miserable": {"t": now}, "Buddy": {"t": now - 200}}
cb.away = {"buddy": now - 150}
cb.rego_when_back = ("Revolution", now - 20)
sent.clear(); b._cool.pop("rego_par", None)
cb._rego_check()
check(f"Buddy's party row is from before the @stop: 'par' to check, @rego still held ({sent}, {regos})",
      "par" in sent and not regos and cb.rego_when_back)
g.party["Buddy"]["t"] = time.time()
cb._rego_check()
check(f"…still in the party 2 min on: @rego goes ahead ({regos})", regos == [1] and cb.rego_when_back is None)
check("…and it's logged", any("still in the party" in l for l in s.logs))

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
