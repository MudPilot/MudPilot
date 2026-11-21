"""Dan, 2026-10-28: mages should deathtouch (dtch) the last monster when it's weak and they're down near the rest
line — a little mana for 50-100 HP, out of the fight without needing to rest. Not on one that hits hard (kill it
fast), not on undead, not with several monsters, not with the mana you'd rest for, not if you don't know dtch."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 55
st.auto_spells = True; st.auto_nuke = True; st.rest_below_hp = 60
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
g, b, w = s.state, s.bot, s.world
g.level, g.max_hp, g.max_ma, g.ma = 55, 830, 519, 400
g.known_spells = ["mmis", "magm", "dtch", "simp"]
weak = next(m for m in w.monsters.values() if m.get("in_game") and not m.get("undead") and m.get("exp", 0) > 500
            and 0 < float((m.get("attack_data") or {}).get("mme_avg") or 0) < 830 * 0.04)
hard = next(m for m in w.monsters.values() if m.get("in_game") and not m.get("undead")
            and float((m.get("attack_data") or {}).get("mme_avg") or 0) > 830 * 0.1)
undead = next(m for m in w.monsters.values() if m.get("in_game") and m.get("undead")
              and 0 < float((m.get("attack_data") or {}).get("mme_avg") or 0) < 830 * 0.04)
def go(rec, hp, mobs=1, ma=400, known=None):
    g.hp, g.ma = hp, ma
    if known is not None:
        g.known_spells = known
    sent.clear(); b._cool.clear(); b._risky = None
    return b._drain_heal((rec["name"], rec), rec, rec["name"].split()[-1], None) if mobs == 1 else False
check(f"weak {weak['name']}, HP 60%: dtch it", go(weak, 500) and sent and sent[0].startswith("dtch"))
check("…HP 85%: still drains, up to the rest max or 90% (Dan, 2026-11-14)", go(weak, 705))
check("…HP 92% (over 90%): no", not go(weak, 765))
check(f"hard-hitting {hard['name']}: no — kill it fast", not go(hard, 500))
check(f"undead {undead['name']}: no — nothing to drain", not go(undead, 500))
check("short of mana (under the rest line): no", not go(weak, 500, ma=60))
check("doesn't know dtch: no", not go(weak, 500, known=["mmis", "magm"]))
g.known_spells = ["mmis", "magm", "dtch", "simp"]
# through fight(): two monsters → the normal pick; the last one → dtch
g.hp = 500
sent.clear(); b._cool.clear(); b.x._casts_this_fight = 0
b.fight([(weak["name"], weak), (weak["name"], weak)])
check(f"two monsters: the usual spell ({sent})", not any(c.startswith("dtch") for c in sent))
sent.clear(); b._cool.clear(); b.x._casts_this_fight = 0
b.fight([(weak["name"], weak)])
check(f"the last one: dtch ({sent})", any(c.startswith("dtch") for c in sent))
# PVE died 2026-10-29 dtch'ing a surf elemental: "Your spell has no effect on surf elemental." every round, HP 537 → dead
surf = next(m for m in w.monsters.values() if m["name"] == "surf elemental")
nonliving = dict(weak, abils={**(weak.get("abils") or {}), 109: 0}, name="test golem")
check("a NonLiving monster (elementals) isn't drained", not go(nonliving, 500))
liv = dict(weak, name="test lizard")
check("a living one is", go(liv, 500))
g.hp = 480; sent.clear(); b._cool.clear()
b._drain_heal((liv["name"], liv), liv, "lizard", None)
g.hp = 400; sent.clear(); b._cool.clear()
check("HP still dropping after 2 drains: stop draining it", not b._drain_heal((liv["name"], liv), liv, "lizard", None))
b._drain_track = None
liv2 = dict(weak, name="test newt")
go(liv2, 500)
b.note_line("Your spell has no effect on test newt.")
check("'Your spell has no effect on …' → never drained again", not go(liv2, 500))
# any spell: "no effect" on a monster → never cast at it again (Dan: standard for all spells)
sb = s.spellbook
magm = sb.find("magm")
sb.note_cast(weak, magm)
sb.feed_line("Your spell has no effect on " + weak["name"] + ".")
check("spellbook remembers magm has no effect on it", sb.useless(weak, magm))
st.monster_spells = {}
g.hp = 830; sent.clear(); b._cool.clear(); b.x._casts_this_fight = 0
b.fight([(weak["name"], weak), (weak["name"], weak)])
check(f"…and doesn't pick it again ({sent})", not any(c.startswith("magm") for c in sent))
# Dan, 2026-11-04: Buddy (Paladin) sent 'dtch serpent' — this session's spell list not read yet (None) = it guessed yes
sb.refused.clear(); sb.no_effect.clear()
g.known_spells = None; st.known_spells = ["mihe"]
check("spell list not read yet: last session's (no dtch) says no", not go(weak, 500))
st.known_spells = []; g.char_class = "Paladin"
check("…none saved either: a Paladin can't learn dtch, no", not go(weak, 500))
g.char_class = "Mage"
check("…a Mage can", go(weak, 500))
g.known_spells = ["dtch"]; go(weak, 500)
sb.feed_line('You say "dtch ' + weak["name"].split()[-1] + '"')
check("game says it as talk ('You say \"dtch …\"'): never cast again", not go(weak, 500))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
