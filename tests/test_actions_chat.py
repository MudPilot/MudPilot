"""Actions (socials) show in the Conversations box: 'You spit.', 'Revolution spits at you!'."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot.chat import ChatLog
c = ChatLog(); c._write = lambda *a: None
ok = True
def check(name, cond):
    global ok; ok &= bool(cond); print(("PASS " if cond else "FAIL ") + name)
check("'You spit.' is an action", c.feed("You spit.") and c.entries[-1][1] == "action")
check("'Revolution spits at you!' — Revolution's", c.feed("Revolution spits at you!") and c.entries[-1][2] == "Revolution")
check("a monster's line isn't", not c.feed("The kobold spits."))
check("combat isn't", not c.feed("You slap the kobold for 12 damage!"))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
