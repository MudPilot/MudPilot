"""A prompt someone types into chat isn't your HP ('Vel gossips: [HP=5/MA=0]:' must not trip a hang-up)."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot.gamestate import GameState
from mudpilot.worlddb import WorldDB
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
g = GameState(WorldDB(":memory:") if False else type("W", (), {"rooms": {}, "by_name": {}, "by_hash": {}, "monsters": {},
                                                                  "monster_names": {}, "items": {}, "item_names": {},
                                                                  "spells": {}, "room": lambda self, k: None})())
g.feed_partial("[HP=684/MA=473]:")
check("real prompt read", g.hp == 684)
g.feed_line([("[HP=684/MA=473]:Vel gossips: [HP=5/MA=0]: ha", None)])
check("a prompt quoted in gossip leaves HP alone", g.hp == 684)
g.feed_line([("Revolution telepaths: [HP=12/MA=0]:", None)])
check("…and in a telepath", g.hp == 684)
g.feed_line([("Sneaking...[HP=650/MA=473]:", None)])
check("a prompt glued to game text still counts", g.hp == 650)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
