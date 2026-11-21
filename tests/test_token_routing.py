"""0.8.201 (Dan): token routing — Go to may 'use' a teleport token you carry (token of Silvermere, of Rhudaur…) when
it saves a lot of walking. Off by default. PVE rules: only with no monsters in the room and out of combat, it's a
spell (a round), it spends a use, and a token that doesn't go falls back to walking. The landing room, level and cash
come from MME (the token's spell textblock: 'nomonsters…minlevel 25…price 200000…teleport 1813 1')."""
import os, sys, tempfile, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_token_routing"))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.megamud_files import path_from_route
from mudpilot.gamestate import RoomView
from mudpilot.tokens import token_table, router, TOKEN_ROOMS
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 55
check("off by default", st.route_tokens is False and st.route_token_min_save == 40 and st.route_token_dest == {})
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
logs = []
s.log = lambda m, *a, **k: logs.append(m)
sent = []
s.send = lambda c, *a, **k: sent.append(c)
b, w, g = s.bot, s.world, s.state

# ---- the data
tab = token_table(w)
silver = next(n for n, it in w.items.items() if it.get("name") == "token of Silvermere")
check(f"token of Silvermere lands on the Pier 1/1813 ({tab.get(silver)})",
      tab.get(silver, {}).get("to") == (1, 1813) and tab[silver]["level"] == 25 and tab[silver]["price"] == 200000
      and tab[silver]["nomonsters"])
names = {v["name"] for v in tab.values()}
check(f"all the town tokens found ({len(tab)})", {"token of Rhudaur", "token of Khazarad", "token of Arlysia",
                                                  "token of Port Blackwater", "token of Kingsport"} <= names)
check("a one-shot (potion of levitation) isn't a token", "potion of levitation" not in names)

ARLYSIA, PIER = (17, 2259), (1, 1813)
nb = next(e.to for e in w.room(PIER).exits.values() if e.to[0] == 1 and e.to != PIER)   # a room next to the Pier
walk = w.route(ARLYSIA, nb)
check(f"Arlysia → next to the Pier is a long walk ({len(walk or [])} rooms)", walk and len(walk) > 100)


def setup(carry="token of Silvermere", level=55, cash=10_000_000, party=None, mons=()):
    g.set_room(ARLYSIA)
    g.carrying, g.keys, g.level, g.wealth = carry, "", level, cash
    g.party = party or {}
    g.in_combat = False
    g.view = RoomView(w.room(ARLYSIA).name, set(), [(m, None) for m in mons], [], [], time.time())
    b._picked_items = set()
    b._cast_sent_at = 0
    tr = router(b)
    tr.failed, tr.blocked, tr.sent, tr.uses, tr.spent_inv = {}, {}, None, {}, {}
    b._goto_target = nb
    mp = path_from_route(w, ARLYSIA, walk, name=f"Go to {nb[0]}/{nb[1]}")
    b.pilot.active, b.pilot.mp, b.pilot.target = True, mp, nb
    b.pilot._reset()
    return mp


def first_step():
    plan = b.pilot._build(ARLYSIA)
    return plan[0] if plan else None, plan


st.route_tokens = False
setup()
s0, plan = first_step()
check("setting off: no token, walks", s0 is not None and getattr(s0, "_token", None) is None and len(plan) == len(walk))

st.route_tokens = True
setup()
s0, plan = first_step()
check(f"on, carrying the token: first step uses it ({s0.move if s0 else None} → {s0.dest if s0 else None})",
      s0 is not None and s0._token == silver and s0.move == "use token of silvermere" and s0.dest == PIER)
check(f"…then walks on from the Pier ({len(plan) - 1} rooms, not {len(walk)})",
      plan[1].room == PIER and plan[-1].dest == nb and len(plan) - 1 < 10)
check("…and says so", any("using the token of Silvermere" in l for l in logs))

setup(carry="")
s0, _ = first_step()
check("not carrying one: walks (never plans with a token you don't have)", getattr(s0, "_token", None) is None)
setup(level=20)
s0, _ = first_step()
check("below the token's level (25): walks", getattr(s0, "_token", None) is None)
setup(cash=1000)
s0, _ = first_step()
check("short of the cash it wants: walks", getattr(s0, "_token", None) is None)
setup(cash=None)
s0, _ = first_step()
check("cash not known yet: walks", getattr(s0, "_token", None) is None)
setup(party={"Tester": {}, "Buddy": {}})
s0, _ = first_step()
check("in a party: walks (a token takes only you)", getattr(s0, "_token", None) is None)
setup(mons=("orc",))
s0, _ = first_step()
check("monsters in the room: walks", getattr(s0, "_token", None) is None)
setup()
g.in_combat = True
s0, _ = first_step()
check("in combat: walks", getattr(s0, "_token", None) is None)

# not worth it: the Pier itself from a few rooms away
setup()
short = w.route(nb, PIER)
b.pilot.target = PIER
tok = router(b).shortcut(nb, PIER, short)
check(f"a short trip ({len(short)} rooms): no token", tok is None)
st.route_token_min_save = len(walk) + 5
setup()
s0, _ = first_step()
check("min save above what it saves: walks", getattr(s0, "_token", None) is None)
st.route_token_min_save = 40

# ---- the walk sends it (once — then waits for where it lands)
mp = setup()
b.path, b.walking, b.idx = mp, True, 0
b.pilot.start(mp)
b.pilot.trusted = ARLYSIA
del sent[:]
for _ in range(3):
    b.walk([], [])
check(f"walk() sends the token use once and waits ({sent})", sent.count("use token of silvermere") == 1)
b.walking, b.path = False, None

# ---- using it
setup()
s0, plan = first_step()
b.pilot.mp.steps[:] = plan
b.idx = 0
b.pilot.need_plan = False
b.pilot.trusted = ARLYSIA
b._cast_sent_at = time.time()
took = b.pilot.prepare()
check("a spell went out this round: waits (a token is a spell — one a round)", took is True
      and "round" in (b.status or "").lower())
b._cast_sent_at = 0
g.view.monsters = [("giant rat", None)]
took = b.pilot.prepare()
nxt = b.pilot.mp.steps[0] if b.pilot.mp.steps else None
check("a monster walked in before it went: walk instead", getattr(nxt, "_token", None) is None
      and any("only works with the room clear" in l for l in logs))
g.view.monsters = []
check("…and that token isn't planned from here for a while", router(b).shortcut(ARLYSIA, nb, walk) is None)

# the game says no → walk
setup()
s0, plan = first_step()
tr = router(b)
tr.hold(s0, ARLYSIA)
s.state.pending = []
b.note_line("You cannot use that here.")
check("a refusal line marks the token failed", silver in tr.failed and tr.sent is None)
s0, _ = first_step()
check("…and the trip walks", getattr(s0, "_token", None) is None)
check("…said once", sum("didn't work" in l for l in logs) == 1)

# a busy round → try again; nothing at all → walk
setup()
s0, plan = first_step()
tr = router(b)
tr.hold(s0, ARLYSIA)
b.note_line("You have already cast a spell this round!")
check("'already… this round' is a retry, not a failure", tr.no_move(s0, ARLYSIA) == "retry" and silver not in tr.failed)
check("no answer, no move: walk", tr.no_move(s0, ARLYSIA) == "walk" and silver in tr.failed)

# chat that sounds like a refusal isn't one
setup()
s0, plan = first_step()
tr = router(b)
tr.hold(s0, ARLYSIA)
b.note_line("Buddy gossips: you can't be serious")
check("a gossip line isn't the token's answer", silver not in tr.failed)

# it worked: counted, and not planned again until 'i' shows it's still there
setup()
s0, plan = first_step()
tr = router(b)
tr.hold(s0, ARLYSIA)
g.set_room(PIER)
g.view_seq += 1
tr.usable(PIER)
check("a use that landed somewhere else counts", len(tr.uses.get(silver, [])) == 1 and tr.sent is None)
g.set_room(ARLYSIA)
check("…and the token isn't planned again before 'i' shows it", tr.shortcut(ARLYSIA, nb, walk) is None)
g.inv_seq += 1
check("…'i' shows it again: plannable", tr.shortcut(ARLYSIA, nb, walk) is not None)
tr.uses[silver] = [time.time()] * 5
check("…5 uses today: spent", tr.shortcut(ARLYSIA, nb, walk) is None)

# a token MME has no landing room for: set it by hand
setup(carry="glowing pebble")
st.route_token_dest = {"glowing pebble": "1/1813"}
got = router(b).carried()
check(f"a hand-set landing room for a token MME doesn't know ({got})",
      any(info["to"] == PIER and info["name"] == "glowing pebble" for _n, info in got))
s0, _ = first_step()
check("…and it's planned with", s0 is not None and s0.move == "use glowing pebble")
st.route_token_dest = {}

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
