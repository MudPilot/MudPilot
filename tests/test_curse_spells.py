"""Curses and boss spells aren't round-by-round attacks (Revolution, 2026-11-03: acid rain on the blood skeletons;
Dan: "Acid tempest is not a combat spell its a curse.. only used really for bosses")."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.spells import fight_spell
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None
s = Session(st); sb = s.spellbook
rain, atem, acid, swar = (sb.find(x) for x in ("rain", "atem", "acid", "swar"))
mob = {"num": 1, "name": "blood skeleton", "hp": 200, "mr": 0, "abils": {}, "exp": 500}
boss = dict(mob, name="prismatic dragon", boss=True)
check("acid rain lasts: never a fight spell", not fight_spell(rain, [mob]) and not fight_spell(rain, [boss]))
check("acid tempest: not on a normal room", not fight_spell(atem, [mob, mob, mob]))
check("acid tempest: yes with a boss here", fight_spell(atem, [boss]))
check("acid jet / swarm unaffected", fight_spell(acid, [mob]) and fight_spell(swar, [mob]))
got = sb.auto_pick([rain, atem], [mob, mob, mob], 50, 10 ** 6, 0.0, 120, 0, "damage", 0)
check(f"auto pick won't hand back rain or tempest ({got and got[0]['Name']})", got is None)
got = sb.auto_pick([rain, atem, swar], [mob, mob, mob], 50, 10 ** 6, 0.0, 120, 0, "damage", 0)
check(f"…takes swarm instead ({got and got[0]['Name']})", got and got[0]["Short"] == "swar")
got = sb.auto_pick([rain, atem], [boss], 50, 10 ** 6, 0.0, 120, 0, "damage", 0)
check(f"boss fight: tempest allowed ({got and got[0]['Name']})", got and got[0]["Short"] == "atem")
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
