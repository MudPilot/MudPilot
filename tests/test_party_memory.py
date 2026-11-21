"""Buddy restarted (Dan, 2026-11-03): Revolution and Evolution had told the old Buddy their stats and never again, so
the new one judged every lair as if alone — the Dirt Path's acid beasts 'deadly', 338 rooms round them to the Frozen
Cavern 28 rooms away. Teammates' last stats are kept till they send newer; a teammate saying hi gets ours again."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
saved = {}
def mk():
    st = config.Settings(); st.my_name = "Buddy"
    st.mpsync_peers = dict(saved.get("peers") or {})
    st.save = lambda: saved.__setitem__("peers", dict(st.mpsync_peers))
    s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
    g = s.state
    g.ac, g.dr, g.max_hp, g.level, g.char_class = 69, 14, 340, 23, "Paladin"
    g.party = {"Buddy": {}, "Evolution": {"class": "Druid"}, "Revolution": {"class": "Priest"}}
    return s
s = mk()
ps = s.partysync
ps.command("Revolution", "me lvl=55 hp=839 ma=454 ac=75 dr=9 dmg=668 cls=Priest str=70")
ps.command("Evolution", "me lvl=21 hp=267 ma=237 ac=63 dr=13 dmg=92 cls=Druid str=60")
check("stats heard", set(ps.info()) == {"Revolution", "Evolution"})
s2 = mk()                                    # restarted: nobody tells it again
inf = s2.partysync.info()
check(f"after a restart still knows them ({sorted(inf)})", inf.get("Revolution", {}).get("dmg") == 668
      and inf.get("Evolution", {}).get("hp") == 267)
check(f"levels too ({s2.partysync.levels()})", s2.partysync.levels() == {"Revolution": 55, "Evolution": 21})
s2.bot.cfg.attack_spells = s2.bot.cfg.attack_spells or "x"
check("the Dirt Path lair isn't dangerous with the party", not s2.bot.danger_room((17, 4)))
# what Buddy really took there on a bad visit (194): measured on his HP, Revolution healing — not flagged (Dan: "Revo
# eats that up"); alone it is
s2.danger.observed = lambda room: 194 if room == (17, 4) else None
s2.bot._danger_key = s2.bot._danger_cache = None
check("Buddy's own bad visit, Revolution healing: not dangerous", not s2.bot.danger_room((17, 4)))
s2.state.party = {"Buddy": {}}
s2.bot._danger_key = s2.bot._danger_cache = None
check("…alone it is", s2.bot.danger_room((17, 4)))
s2.state.party = {"Buddy": {}, "Evolution": {"class": "Druid"}, "Revolution": {"class": "Priest"}}
s2.partysync.command("Evolution", "me lvl=22 hp=280 ma=240 ac=63 dr=13 dmg=95 cls=Druid")
check("a newer update replaces it", mk().partysync.info()["Evolution"]["hp"] == 280)
# a teammate (re)starting says hi: we tell them about us again
ps._told_me = {"evolution": "lvl=23", "revolution": "lvl=23"}
ps.command("Evolution", "hi tune lvl=22")
check(f"hi → ours goes again ({sorted(ps._told_me)})", "evolution" not in ps._told_me and "revolution" in ps._told_me)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
