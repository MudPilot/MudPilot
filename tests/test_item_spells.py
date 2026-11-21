"""Item spells as commands (MegaMUD's '#etc'): the swap is done for you — Dan's priest with an amber scepter in hand
and a large silvery cross off-hand, casting with the two-handed emerald-tipped crozier."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.worlddb import WorldDB
from mudpilot import itemspells as I
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
w = WorldDB(os.path.join(here, "mudpilot", "bundled", "Paradigm.db"))
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
t = I.table(w)
check("#etc = emerald-tipped crozier", any(g["name"] == "emerald-tipped crozier" for g in t.get("#etc", [])))
check("#lsc = large silvery cross", any(g["name"] == "large silvery cross" for g in t.get("#lsc", [])))
check("no command for the teak wand (10 uses)", not any(g["name"] == "teak wand" for v in t.values() for g in v))
inv = ("amber scepter (Weapon Hand), large silvery cross (Off-Hand), emerald-tipped crozier, "
       "3 black diamonds, 2 rations")
seq = I.expand(w, "#etc", inv)
check(f"two-hander: off-hand off, crozier on, use, both back ({seq})", seq == [
    "remove large silvery cross", "eq emerald-tipped crozier", "use emerald-tipped crozier",
    "eq amber scepter", "eq large silvery cross"])
check("with a target", I.expand(w, "#etc Miserable", inv)[2] == "use emerald-tipped crozier Miserable")
check("already holding it: just use", I.expand(w, "#lsc orc", inv) == ["use large silvery cross orc"])
inv2 = "amber scepter (Weapon Hand), large silvery cross, emerald-tipped crozier"
check(f"off-hand item not worn: on, use, off ({I.expand(w, '#lsc', inv2)})",
      I.expand(w, "#lsc", inv2) == ["eq large silvery cross", "use large silvery cross", "remove large silvery cross"])
check("not an item spell: left alone", I.expand(w, "#zzzq", inv) is None and I.expand(w, "mmis orc", inv) is None)
check(f"listed for what you carry ({I.carried(w, inv)})", ("#etc", "divine intervention", "emerald-tipped crozier")
      in I.carried(w, inv))
# through the session: the spell list knows it, and the bot's cast goes out as the swap
st = config.Settings(); st.save = lambda: None
s = Session(st); s.world = w; s.state.world = w; s.spellbook.world = w; s._no_log_file = True
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True
s.state.carrying = inv
sp = s.spellbook.find("#etc")
check(f"spell book: #etc is divine intervention ({sp and sp['Name']})", sp and sp["Name"] == "divine intervention")
s.bot.send(st.cast_cmd.format(short="#etc", target="").strip())
check(f"bot cast sends the swap ({sent})", sent[:3] == ["remove large silvery cross", "eq emerald-tipped crozier",
                                                         "use emerald-tipped crozier"] and len(sent) == 5)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
