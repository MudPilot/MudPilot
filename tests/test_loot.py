"""Cash rules by level, drop smaller coins, auto-grab items, stash each lap."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.megamud_files import path_from_route
st = config.Settings(); st.save = lambda: None
st.my_name = "Tester"; st.auto_spells = False; st.auto_combat = False; st.auto_rest = False; st.auto_bless = False
st.loot_cash = True; st.auto_loot = True; st.loot_items = ["longsword"]
s = Session(st)
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T(); s._want_connected = True
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
def tick(n=1):
    for _ in range(n):
        s.bot._cool = {"par": time.time(), "par_solo": time.time()}; s.bot._loot_wait = None; s.bot.tick()
s.state.max_hp = s.state.hp = 600
s.state.level = 6
feed("[HP=600/MA=300]:Town Gates", "You notice 40 copper farthings, 12 gold crowns, a mithril longsword here.",
     "Obvious exits: north, south")
sent.clear(); tick()
check(f"level 6: skips copper, takes gold and the sword ({sent})",
      "get 12 gold crowns" in sent and not any("copper" in c for c in sent) and "get mithril longsword" in sent)
# heavy: drop copper before picking up gold
s.state.coins = {"copper farthing": 300, "silver noble": 20}; s.state.enc = (1500, 2400, "Medium", 62)
feed("[HP=600/MA=300]:Town Gates", "You notice 5 gold crowns here.", "Obvious exits: north, south")
sent.clear(); tick()
check(f"heavy: drops just enough copper first (0.8.201: only as many as the pile needs) ({sent})",
      sent[:1] == ["drop 5 copper farthings"] and "get 5 gold crowns" in sent)
# stash room
s.state.enc = (500, 2400, "Light", 20)
feed("You picked up 5 gold crowns.", "You picked up a mithril longsword.")
s.state.coins["gold crown"] = 17
s.state.carrying = "17 gold crowns, a mithril longsword, woodland robes (Worn)"
here = s.state.room or (1, 1)
s.state.set_room((1, 1)); st.stash_room = "1/1"
st.item_rules = list(st.item_rules or []) + ["mithril longsword: get, stash"]   # 0.8.200: only Auto-stash items
s.bot.walking = True                     # (0.8.201: only while looping / walking, never standing there by hand)
sent.clear(); tick()
s.bot.walking = False
check(f"in the stash room: hides gold and the sword straight from the pack ({sent})",
      "hide 17 gold crowns" in sent and "hide mithril longsword" in sent and not any(c.startswith("drop") for c in sent)
      and not any("robes" in c for c in sent))
# lap end: loop that doesn't pass the stash room -> goes there, then back to the loop
st.stash_room = "1/224"
s.state.coins["gold crown"] = 40
w = s.world
lp = path_from_route(w, (1, 3), w.route((1, 3), (1, 16)) + w.route((1, 16), (1, 3)), name="Loop")
went = s.bot.x.stash_at_lap_end(lp)
check(f"end of lap: walks to the stash room and back ({s.bot.path.title if s.bot.path else None})",
      went and s.bot.path and s.bot.path.title.startswith("Go to") and s.bot.after_goto is lp)
s.bot.stop()
s.state.coins["gold crown"] = 2      # 200 copper worth < 500 minimum, no items
s.bot.x.looted.clear(); st.loot_items = []; st.stash_looted = False
st.item_rules = [r for r in st.item_rules if not r.startswith("mithril longsword")]
check("not worth a trip under the minimum", not s.bot.x.stash_at_lap_end(lp))
print("ALL PASS" if ok else "SOME FAILED")
st.stash_room = "1/1"; s.state.set_room((1, 1)); st.stash_looted = True
feed("[HP=600/MA=300]:Town Gates", "You notice 17 gold crowns, a mithril longsword here.", "Obvious exits: north, south")
s.state.set_room((1, 1)); sent.clear(); s.bot._looted_seq = -1; s.bot.loot()
check(f"doesn't pick its own stash back up ({sent})", not any(c.startswith("get") for c in sent))
# per-loop stash, and never a 300-room trip
s.state.coins["gold crown"] = 40
s.state.set_room((1, 3))
st.stash_room = "1/224"; st.stash_max_steps = 3
check("default stash too far → doesn't go", not s.bot.x.stash_at_lap_end(lp))
st.loop_stash = {s.bot.x.loop_key(lp): "1/1"}; st.stash_max_steps = 40
check(f"this loop's own stash wins ({s.bot.x.stash_room(lp)})", s.bot.x.stash_room(lp) == (1, 1))
s.bot._lap_path = lp
check("stash_room() follows the loop you're running", s.bot.x.stash_room() == (1, 1))
print("ALL PASS" if ok else "SOME FAILED")
