"""Party sync 'about me' (Dan, 2026-10-28): MudPilots in a party tell each other level, max HP/mana, AC/DR, best
spell damage and class, so the leader judges a lair by the party — risky for one, easy for three (they kill it
faster) — and by the weakest member's HP (a 52-HP Buddy died following Miserable into the orc barracks)."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 47; st.char_class = "Mage"
st.party_sync = True
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = T(); s._entered = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g, b, ps = s.state, s.bot, s.partysync
g.level, g.max_hp, g.max_ma, g.ac, g.dr = 47, 674, 519, 60, 8
g.known_spells = ["mmis", "magm", "simp", "dfir", "esto"]
g.char_class = "Mage"
g.party = {"Miserable": {}, "Revolution": {}}
info = ps.my_info()
check(f"tells the party about itself ({info})", "lvl=47" in info and "hp=674" in info and "dmg=" in info and "cls=Mage" in info)
ps.command("Revolution", "me lvl=47 hp=847 ma=408 ac=66 dr=15 dmg=520 cls=Druid")
check(f"reads a member's ({ps.info()})", ps.info().get("Revolution", {}).get("hp") == 847)
# the party's damage makes a lair less dangerous
room = (15, 1539)                                   # Webbed Mine Chamber, up to 6 wraith spiders
ps.peers["Revolution"]["me"]["dmg"] = 0
b._danger_cache = None
solo, _n, _w = b.lair_danger(room)
ps.peers["Revolution"]["me"]["dmg"] = 2500          # a heavy-hitting party
b._danger_cache = None
team, _n, _w = b.lair_danger(room)
check(f"the party kills it faster: less damage to you ({solo:.0f} → {team:.0f})", team < solo * 0.6)
# the weakest member's HP is the line
ps.peers["Revolution"]["me"].update(hp=52, dmg=0)
b._danger_cache = None
check(f"weakest member's HP is the line ({b._weakest_hp()})", b._weakest_hp() == 52)
check("…so a lair that's fine for Miserable is dangerous with a 52-HP member along",
      b.danger_room((15, 183)) or b.danger_room(room))
# it's sent once, then again only when something changes
g.party = {"Miserable": {}, "Revolution": {}}
ps.peers["Revolution"]["t"] = time.time()
ps.asked = {"revolution"}
sent.clear(); ps._me_checked = 0; ps.tick()
check(f"sends '@mpsync me …' ({[x for x in sent if 'mpsync me' in x]})", any("@mpsync me " in x for x in sent))
sent.clear(); ps._me_checked = 0; ps.tick()
check("…not again while nothing changed", not any("@mpsync me " in x for x in sent))
g.ac = 68                                           # a bless: AC wobbles — not worth a telepath
sent.clear(); ps._me_checked = 0; ps.tick()
check("…not for a bless moving AC a little", not any("@mpsync me " in x for x in sent))
g.ac = 60
g.max_hp = 690
sent.clear(); ps._me_checked = 0; ps.tick()
check("…once per teammate — not again even for a change (Dan)", not any("@mpsync me " in x for x in sent))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
