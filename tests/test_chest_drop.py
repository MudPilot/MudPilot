"""0.8.201 chest loot: cheap loot is left / dropped, only valuable chest loot goes on the sell trip (chestloot.py)."""
import os, sys, time, shutil, tempfile
_tmp = tempfile.mkdtemp()
os.environ["MUDPILOT_DATA_DIR"] = os.path.join(_tmp, "data")      # never the real data folder
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.chestloot import sell_copper
db = os.path.join(_tmp, "world.db")
shutil.copy2(os.path.join(config.BUNDLED_DIR, "Paradigm.db"), db)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.board = "Paradigm"
st.auto_combat = False; st.auto_rest = False; st.auto_bless = False; st.auto_spells = False
s = Session(st, world_path=db); s._no_log_file = True
sent, logs = [], []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
s.log = lambda m, *a, **k: logs.append(m)
b, w, cl = s.bot, s.world, s.chestloot
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)

check("default off", config.Settings().loot_drop_cheap is False and config.Settings().loot_drop_below_gold == 100)
check("Paradigm sell = half base, charm 50", sell_copper(10000, 50, True) == 5000)
check("Paradigm charm 60 pays 2% more", sell_copper(10000, 60, True) == 5100)
check("stock charm 50 = 50%", sell_copper(10000, 50, False) == 5000)
s.state.charm = 50
v = cl.value("agate stone")
check(f"agate stone (10 gold base) sells for 5 gold ({v})", v == 500)
check(f"aquamarine stone sells for 250 gold ({cl.value('aquamarine stone')})", cl.value("aquamarine stone") == 25000)
check("unknown item → no value", cl.value("glowing frobnicator") is None)
check("price 0 → no value", cl.value("stone key") is None or w.items[344]["price"] > 0)
s.state.carrying = "torch, agate stone, aquamarine stone, oak chest, iron key"

# ---- off: nothing changes
check("off → nothing is cheap", not cl.cheap("agate stone"))
st.loot_drop_cheap = True
check("on → agate stone is cheap", cl.cheap("agate stone"))
check("aquamarine stone isn't", not cl.cheap("aquamarine stone"))
check("a key is never dropped", not cl.cheap("iron key") and cl.protected("iron key"))
check("a container is never dropped", cl.protected("oak chest"))
check("a light is never dropped", cl.protected("torch"))
st.item_rules = ["agate stone: get"]
check("an item rule protects it", not cl.cheap("agate stone") and "rule" in cl.protected("agate stone"))
st.item_rules = ["agate stone: stash"]
check("a stash rule protects it", not cl.cheap("agate stone"))
st.item_rules = []
s.state.carrying = "agate stone (Worn)"
check("gear you wear is protected", cl.protected("agate stone") == "you wear it")
s.state.carrying = "torch, agate stone"
st.auto_buy = "agate stone 1-2"
check("on the restock list → protected", cl.protected("agate stone"))
st.auto_buy = ""
q = next(iter(cl._quest_items()), None)
check(f"quest items found ({len(cl._quest_items())})", q is not None and cl.protected(w.items[q]["name"]))

# ---- loot: cheap floor items are left, valuable ones picked up
st.auto_loot = True; st.loot_items = ["stone"]
room0 = (1, 300) if (1, 300) in w.rooms else next(iter(w.rooms))
s.state.candidates = [room0]
s.state.view = RoomView("x", {"N"}, items=[(1, "agate stone"), (1, "aquamarine stone")])
s.state.view_seq += 1
b._looted_seq = -1; b._loot_wait = None
sent.clear()
b.loot()
check(f"leaves the agate, gets the aquamarine ({sent})",
      any("aquamarine" in x for x in sent) and not any("agate" in x for x in sent))
check(f"says why ({[l for l in logs if 'Leaving' in l]})", any("Leaving the agate stone" in l for l in logs))
st.loot_drop_cheap = False
s.state.view_seq += 1; b._looted_seq = -1; b._loot_wait = None; b._loot_asked = None; b._no_item = {}; sent.clear()
b.loot()
check(f"off → both picked up ({sent})", any("agate" in x for x in sent) and any("aquamarine" in x for x in sent))
st.loot_drop_cheap = True

# ---- a chest opened: before / after read
s.state.carrying = "oak chest, 2 agate stone"
sent.clear()
s.send("open oak chest")
check("open goes out", "open oak chest" in sent)
check("before read taken", cl._open and cl._open["before"].get("agate stone") == 2)
cl._open["t"] -= 5
cl.tick()
check(f"'i' asked after the open ({sent})", sent[-1] == "i")
s.state.carrying = "4 agate stone, aquamarine stone, glowing frobnicator, iron key"
s.state.inv_seq += 1
sent.clear(); logs.clear()
cl.tick()
check(f"drops only the 2 new agate stones ({sent})", sent == ["drop 2 agate stone"])
check(f"keeps the aquamarine to sell ({cl.ledger})", cl.ledger.get("aquamarine stone") == 1)
check("unknown item left alone", "glowing frobnicator" not in cl.ledger and not any("frob" in x for x in sent))
check("key left alone", "iron key" not in cl.ledger and not any("key" in x for x in sent))
check(f"logged ({logs})", any("dropped" in l for l in logs) and any("keeping to sell" in l for l in logs))
sent.clear()
s.send("open north door")
check("a door isn't a chest", cl._open is None)

# ---- sell trip: the valuable chest loot, not the cheap listed items
st.auto_sell_on = True; st.auto_sell_items = ["agate stone"]
s.state.carrying = "2 aquamarine stone, 4 agate stone"
T = s.trips
shop_rooms = {}
T.shops_for = lambda item: [(1, 500)] if "stone" in item else []
T._nearest = lambda rooms, lim: (rooms[0], 3) if rooms else (None, None)
trip = T.next_trip()
check(f"sell trip sells 1 aquamarine (what the chest gave), no agate ({trip})",
      trip and trip[0] == "sell" and trip[2] == ["sell aquamarine stone"])
st.loot_drop_cheap = False
trip = T.next_trip()
check(f"off → the listed agate goes as before, chest loot doesn't ({trip})",
      trip and trip[2] == ["sell agate stone"] * 4)
st.loot_drop_cheap = True
s.state.carrying = "4 agate stone"
cl.to_sell(T.carried())
check("sold → off the list", "aquamarine stone" not in cl.ledger)

shutil.rmtree(_tmp, ignore_errors=True)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
