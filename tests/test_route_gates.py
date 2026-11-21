"""Routing gates: class / race / alignment / ability / toll / traps, and the whole party."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot.worlddb import WorldDB, Exit
w = WorldDB(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "mudpilot", "bundled", "Paradigm.db"))
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
def ex(etype, kind="restricted"):
    to = next(iter(w.rooms))
    return Exit("N", to, etype, True, False, kind)
w.char = {"class": 13, "race": 2, "align": "Good", "abil": lambda a: {200: 5}.get(a), "wealth": 100}
check("class 13 OK → mage (13) passes", w.can_use(ex("(Class: 13 OK, 0 NO)")))
w.char["class"] = 4
check("…a class-4 doesn't", not w.can_use(ex("(Class: 13 OK, 0 NO)")))
w.char["class"] = 13; w.char["party_classes"] = [4]
check("…and neither does a party with a class-4 in it", not w.can_use(ex("(Class: 13 OK, 0 NO)")))
w.char["party_classes"] = []
check("alignment Good within Saint..Seedy", w.can_use(ex("(Alignment: Saint to Seedy)")))
check("alignment Good not within Neutral..Fiend", not w.can_use(ex("(Alignment: Neutral to Fiend)")))
check("ability 200 = 5 within 4..999", w.can_use(ex("(Ability: 200 w/value 4 to 999)")))
check("ability unknown → closed", not w.can_use(ex("(Ability: 134 w/value 2 to 999)")))
check("toll 5 affordable", w.can_use(ex("(Toll: 5)", "toll")))
check("toll 80000 not", not w.can_use(ex("(Toll: 80000)", "toll")))
check("spell trap closed by default", not w.can_use(ex("(Spell Trap: 905)")))
check("trap costs more than a normal step", w.exit_cost(ex("(Trap, 40 damage)", "trap")) > 4)
w.char = {}
check("nothing known about you → gates stay closed", not w.can_use(ex("(Class: 13 OK, 0 NO)")))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
