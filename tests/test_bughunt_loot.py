"""0.8.201 bug hunt (routing_loot.md, gear_shops.md): loot, coins, stash rooms, tolls, shop trips, regen-gear swaps,
redress, errand shops and @makeroom."""
import os, sys, tempfile, time
from types import SimpleNamespace as NS
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
os.environ.setdefault("MUDPILOT_DATA_DIR", os.path.join(tempfile.gettempdir(), "mudpilot_test_bughunt_loot"))
from mudpilot import config, gearswap
from mudpilot.gamestate import RoomView
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

st = config.Settings(); st.save = lambda: None; st.my_name = "Tester"; st.char_level = 20
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda m, *a, **k: None
b, w, g, x = s.bot, s.world, s.state, s.bot.x
sent = []
b.send = sent.append
x.send = sent.append
s.send = lambda c, **k: sent.append(c)
b.log = lambda *a, **k: None
g.level = 20

# --- #1 drop smaller coins: never a whole pile of gold for one platinum
st.drop_small_coins, st.drop_coins_enc = True, 50
st.stash_coins = ["gold crown", "platinum piece", "runic coin"]
g.enc = (550, 1000, "Medium", 55)
g.coins = {"gold crown": 300, "copper farthing": 40}
r = x.make_room_for("platinum piece", 1)
check(f"1 platinum: drops 1 copper, never the 300 gold (stash coin) ({r})", r == ["drop 1 copper farthing"])
g.coins = {"gold crown": 300}
check(f"only gold to drop: nothing dropped ({x.make_room_for('platinum piece', 1)})",
      x.make_room_for("platinum piece", 1) == [])
st.stash_coins = []
g.coins = {"gold crown": 300}
check(f"gold not a stash coin: 1 gold for 1 platinum, not all 300 ({x.make_room_for('platinum piece', 1)})",
      x.make_room_for("platinum piece", 1) == ["drop 1 gold crown"])
g.coins = {"silver noble": 300}
check(f"never worth more than what's picked up: 300 silver for 2 gold ({x.make_room_for('gold crown', 2)})",
      x.make_room_for("gold crown", 2) == ["drop 2 silver nobles"])
g.coins = {"copper farthing": 300}
check(f"5 gold crowns: only 5 copper dropped ({x.make_room_for('gold crown', 5)})",
      x.make_room_for("gold crown", 5) == ["drop 5 copper farthings"])
st.stash_coins = ["gold crown", "platinum piece", "runic coin"]

# --- #5 stash safety: every stash room counts, and auto-search skips them
st.stash_room, st.loop_stash, st.party_stash_room = "1/10", {"other.mp": "2/20"}, "3/30"
check("default, another loop's and the party stash all count",
      x.in_any_stash((1, 10)) and x.in_any_stash((2, 20)) and x.in_any_stash((3, 30)) and not x.in_any_stash((4, 40)))
g.candidates = [(2, 20)]
g.view = RoomView("Somewhere", {"N"}, items=[(300, "gold crowns")])
g.view_seq += 1
g.enc = (100, 1000, "None", 10)
st.loot_cash = True
sent.clear()
b._looted_seq = -1
b._loot_wait = None
b.loot()
check(f"another loop's stash room: its gold isn't picked up ({sent})", not any("gold" in c for c in sent))

# --- #6 several items in one look: the second checked against what the first already takes
w.item_names["test bracers"] = {"name": "test bracers", "encum": 50}
w.item_names["test chainmail"] = {"name": "test chainmail", "encum": 50}
g.enc = (940, 1000, "Heavy", 94)
check("first fits (60 free)", b.how_many_fit("test bracers", 1) == 1)
check("second doesn't, with the first's 50 queued", b.how_many_fit("test chainmail", 1, 50) == 0)

# --- #9 copper looted counts what the game says you picked up
g.copper_looted = 0
g._scan_status_lines("You picked up 3 gold crowns.")
check(f"'You picked up 3 gold crowns' → 300 copper looted ({g.copper_looted})", g.copper_looted == 300)

# --- #4 tolls add up
toll = next(((k, d) for k, r in w.rooms.items() for d, e in r.exits.items() if e.kind == "toll"
             and "Toll: 300" in (e.etype or "")), None) or \
    next(((k, d) for k, r in w.rooms.items() for d, e in r.exits.items() if e.kind == "toll"), None)
amt = int(__import__("re").search(r"Toll:\s*(\d+)", w.rooms[toll[0]].exits[toll[1]].etype).group(1))
mp = NS(steps=[NS(room=toll[0], dir=toll[1]), NS(room=toll[0], dir=toll[1])])
check(f"two crossings of a {amt} toll: {2 * amt} needed ({b.path_toll(mp)})", b.path_toll(mp) == 2 * amt)

# --- #8 / gear #9: death forgets coins, encumbrance and the rest swap
g.coins, g.enc = {"gold crown": 5}, (10, 100, "None", 10)
b._swap, b._swap_back, b._swap_rested = "rest", ["eq runed cape"], True
st.swap_owed = ["eq runed cape"]
b._death_at = 0
b.on_death()
check(f"death: coins {g.coins}, enc {g.enc}, swap {b._swap}, owed {st.swap_owed}",
      g.coins == {} and g.enc is None and b._swap is None and b._swap_back == [] and st.swap_owed == [])

# --- #7 route_around rejoins at the next visit, not the first
w.fail_edge = lambda *a: None
b.back_route = lambda a, t: [NS(dir="N", to=t)]
b._send_exit = lambda e: None
hub, other = (1, 382), (1, 383)
b.path = NS(title="Loop", steps=[NS(room=hub, dest=other, dir="E"), NS(room=other, dest=(1, 384), dir="E"),
                                  NS(room=(1, 384), dest=hub, dir="W"), NS(room=hub, dest=other, dir="E"),
                                  NS(room=other, dest=(1, 384), dir="E")])
b.idx = 3
b.route_around(hub, "E", "locked")
check(f"rejoined at the next visit (idx {b.idx}, not 1)", b.idx == 4)
b.path, b.detour = None, None

# --- gear #2 sell math counts the pack only
g.carrying = "platinum ring (Finger), platinum ring, 3 grey potions"
check(f"worn ring not counted ({s.trips.carried()})", s.trips.carried().get("platinum ring") == 1)

# --- gear #1 a trip that changed nothing goes on a cooldown
T = s.trips
t = {"kind": "buy", "checked": True, "items": ["healing potion"], "have0": {"healing potion": 0}, "wealth0": 5}
g.carrying = "platinum ring (Finger)"
T._note_result(t)
check("failed buy remembered", T.failed_lately("buy", "healing potion"))
st.auto_buy_on, st.auto_buy, st.auto_deposit_on, st.auto_sell_on = True, "healing potion 3-10", False, False
T._nearest = lambda rooms, lim: ((1, 1), 3)
check("…and next lap doesn't go again", T.next_trip() is None)
T._failed = {}
pots = [n for n, it in w.items.items() if (it.get("name") or "").lower() == "healing potion"]
if pots and T.price_of("healing potion"):
    g.wealth = 0
    check(f"can't afford one ({T.price_of('healing potion')} copper): no trip", T.next_trip() is None)
    g.wealth = 10 ** 7
    check("can afford: the trip's on", T.next_trip() is not None)
g.wealth = None

# --- gear #7 two worn rings with the same name are two rings
fake = NS(items={1: {"name": "platinum ring"}, 2: {"name": "white gold ring"}},
          gear={1: {"Worn": 5, "abils": {}}, 2: {"Worn": 5, "abils": {123: 25}}})
pre, post, notes = gearswap.plan(fake, "platinum ring (Finger), platinum ring (Finger), white gold ring", 1.0, 0.1)
check(f"swap one platinum for the white gold ({pre} / {post})",
      pre == ["remove platinum ring", "eq white gold ring"] and post == ["remove white gold ring", "eq platinum ring"])
pre, post, notes = gearswap.plan(fake, "platinum ring (Finger), 2 white gold ring", 1.0, 0.1)
check(f"a pack stack counts too: one free finger + one swap ({pre})",
      pre.count("eq white gold ring") == 2)

# --- gear #3 / #4 / #8 redress
R = b.redress if hasattr(b, "redress") else None
from mudpilot.redress import Redress, _pack_counts
R = Redress(b)
check(f"pack counts ({dict(_pack_counts('2 platinum ring, platinum ring (Finger), cape'))})",
      _pack_counts("2 platinum ring, platinum ring (Finger), cape") == {"platinum ring": 2, "cape": 1})
st.last_worn = ["platinum ring", "platinum ring", "robe", "boots", "gloves", "cape"]
g.carrying = "platinum ring (Finger), robe (Torso), boots (Feet), gloves (Hands), cape (Back), platinum ring"
sent.clear()
R._put_back(__import__("mudpilot.gamestate", fromlist=["x"]).worn_list(g.carrying), st.last_worn)
check(f"second same-name ring goes back on ({sent})", "eq platinum ring" in sent)
R.login_checked = R.login_checked_swap = True
g.inv_seq, g.dead, g.resting = 5, False, False
b._swap = None
R._saved_at = 0
g.carrying = "robe (Torso), boots (Feet), gloves (Hands), cape (Back), helm (Head)"
st.last_worn = ["robe", "boots", "gloves", "cape", "helm", "amulet", "ring"]
R.tick()
check(f"a strict part of the remembered set doesn't replace it ({st.last_worn})", "amulet" in st.last_worn)
b._swap = "rest"
g.carrying = "shawl (Back), robe (Torso), boots (Feet), gloves (Hands), helm (Head)"
R._saved_at = 0
R.tick()
check(f"in the regen set: not remembered ({st.last_worn})", "shawl" not in st.last_worn)
b._swap = None
R.tick()
check("fully dressed in a different set: remembered", "shawl" in st.last_worn)
st.swap_owed = ["eq runed cape"]
R.login_checked_swap = False
sent.clear()
R.tick()
check(f"owed swap from before a restart replayed at login ({sent}, {st.swap_owed})",
      "eq runed cape" in sent and st.swap_owed == [])

# --- gear #5 errand shop: out of stock isn't "no cash"
E = b.errands
E.active = {"todo": [{"kind": "shop", "num": 1, "room": (1, 1)}]}
E.note_line("You cannot afford log raft.")
check("our own buy: 'cannot afford' noted as money", E.active["todo"][0].get("broke"))
E.active = None

# --- gear #6 @makeroom drops only what's needed, never below the price
g.enc, g.wealth = (95, 100, "Heavy", 95), 2000
g.coins = {"copper farthing": 0, "silver noble": 0, "gold crown": 20}
s.trips.price_of = lambda item: 1500
s.remote._room = {"item": "log raft", "need": 10, "t": time.time(), "dropped": [], "shop": True}
sent.clear()
s.remote._room_tick()
check(f"5 short → 15 coins at most, keeping 1,500 copper for the raft ({sent})", "drop 5 gold crowns" in sent)
s.remote._room = None

# --- #2 alignment gates: the whole party
ex = NS(etype="(Alignment: Saint to Good)", kind="restricted")
w.char = {"align": "Good", "party_aligns": ["Seedy"]}
check("Good leader, Seedy follower: refused", w.gate_ok(ex) is False)
w.char = {"align": "Good", "party_aligns": ["Saint", ""]}
check("Good leader, Saint follower (and one unknown): through", w.gate_ok(ex) is True)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
