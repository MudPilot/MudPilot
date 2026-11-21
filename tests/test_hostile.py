"""Only hostile (evil) MME monsters are attacked; guards/mayor/shopkeepers only if they start it."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None
s = Session(st); b = s.bot
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
def mon(align, exp=50, name="x", typ=0):
    return {"num": 1, "name": name, "exp": exp, "hp": 10, "align": align, "type": typ}
s.state.view = RoomView("Town", {"north"}, monsters=[("guardsman", mon(4, name="guardsman")),
                                                   ("shopkeeper", mon(3, name="shopkeeper", typ=3)),
                                                   ("kobold slave", mon(3, name="kobold slave")),
                                                   ("Mayor Godfrey", mon(0, 1000, "Mayor Godfrey")),
                                                   ("giant rat", mon(2, name="giant rat"))])
names = lambda: [x for x, _ in b.attackable()]
check(f"only the rat ({names()})", names() == ["giant rat"])
st.attack_neutral = True
check("neutral on → shopkeeper and slave too", "shopkeeper" in names() and "kobold slave" in names() and "guardsman" not in names())
st.attack_neutral = False; st.attack_good = True
check("good on → guards and mayor", "guardsman" in names() and "Mayor Godfrey" in names())
st.attack_good = False
b.note_line("The guardsman lunges at you with his halberd for 12 damage!")
check(f"a guard that attacks us is fought back ({names()})", "guardsman" in names())
st.only_mobs = ["shopkeeper"]
check("explicit Only attack list wins", names() == ["shopkeeper"])
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
