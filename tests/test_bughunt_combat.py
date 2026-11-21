"""0.8.201 bug hunt (combat.md #1-12, room_tracking.md F1/F2): each fix checked against a Session with the bundled
MME data and lines fed the way the game sends them."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
from mudpilot.spells import class_spells, is_attack_spell

ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)


def new(cls_name=None, lvl=None, name="Bob"):
    st = config.Settings(); st.save = lambda: None; st.my_name = name
    s = Session(st); s._no_log_file = True
    s.spellbook.memory_path = None
    s.spellbook._save_memory = lambda: None          # never write spell_memory.json from a test
    b, g = s.bot, s.state
    sent = []
    b.send = lambda c, late_ok=False: sent.append(c)
    st.auto_combat = True
    if cls_name:
        w = s.world
        st.char_class = g.char_class = cls_name
        st.char_level = g.level = lvl
        cls = next(k for k, v in w.classes.items() if v["Name"] == cls_name)
        sps = [sp for sp in class_spells(w, cls, lvl) if is_attack_spell(sp)]
        st.known_spells = [sp["Short"] for sp in sps]
        st.known_spell_rows = [[sp["Short"], sp["Name"], int(sp.get("ReqLevel") or 0), int(sp.get("ManaCost") or 0)]
                               for sp in sps]
        g.known_spells = st.known_spells
        st.auto_spells = True; st.attack_spells = []; st.aoe_safety = False
        g.ma = g.max_ma = 400; g.hp = g.max_hp = 600
    return s, st, b, g, sent


def reset(b, g):
    b._cool = {}; b._last_spell = None; b._cast_target = None; b._melee_on = False
    b._attack_sent_at = 0; b._cast_sent_at = 0; b._kill_at = 0; g.in_combat = False


def mon(s, name):
    return next(r for r in s.world.monsters.values() if r["name"] == name)


# 1. a level-55 druid / priest against a high-MR monster: casts something, doesn't stand there
for cls in ("Druid", "Priest"):
    s, st, b, g, sent = new(cls, 55)
    stuck = []
    for nm in ("aged earth dragon", "horned demon"):
        rec = mon(s, nm)
        reset(b, g); sent.clear()
        b.fight([(nm, rec)])
        if not sent:
            stuck.append((nm, b.status))
    check(f"#1 level-55 {cls} vs high-MR monsters acts ({stuck})", not stuck)

# 2 / 3. weapon-immune ghost
s, st, b, g, sent = new()
st.auto_spells = False; st.attack_spells = []
g.carrying = "longsword (Weapon Hand)"
ghost = {"name": "ghost", "exp": 500, "hp": 80, "align": 1, "num": 1}
orc = {"name": "orc", "exp": 100, "hp": 40, "align": 1, "num": 2}
b._melee_target = "ghost"
b.note_line("Your weapon has no effect against this monster!")
reset(b, g); sent.clear()
b.fight([("ghost", ghost), ("orc", orc)])
check(f"#2 ghost first, orc second: swings at the orc ({sent})", sent == ["a orc"])
reset(b, g); sent.clear()
r = b.fight([("ghost", ghost)])
check(f"#2 only the ghost: nothing sent, fight() says walk on ({sent}, {r})", not sent and r is False)
b._melee_immune = {}
reset(b, g); sent.clear()
b.fight([("ghost", ghost)])
g.in_combat = True
b.note_line("Your weapon has no effect against this monster!")
sent.clear(); b._cool = {}
b.fight([("ghost", ghost)])
check(f"#3 'no effect' after our own swing: breaks off with break_cmd ({sent})", sent == [st.break_cmd or "brea"])
# fighting the orc (which it can hurt) with an immune ghost listed first: keep at the orc
reset(b, g); sent.clear()
g.in_combat, b._melee_on, b._melee_target = True, True, "orc"
b._melee_immune = {"ghost": ""}
b.fight([("ghost", ghost), ("orc", orc)])
check(f"#3 already swinging at the orc: no break ({sent})", not sent)
b._attack_cmd = ("a orc", time.time() - 10)
b.note_line("*Combat Off*")
check("#3/#8 *Combat Off* clears the melee state", not b._melee_on and b._melee_target is None)

# 8. manual fight: the 'no effect' is the monster you typed at
b._melee_immune = {}
b._melee_target = "orc"
g.view = RoomView("Somewhere", {"N"}, [("orc", orc), ("ghost", ghost)], [], [], time.time())
b.manual.mob = "ghost"
b.note_line("Your weapon has no effect against this monster!")
check(f"#8 manual fight: the ghost is immune, not the orc ({b._melee_immune_now()})",
      "ghost" in b._melee_immune_now() and "orc" not in b._melee_immune_now())
b.manual.mob = None

# 4. an area spell's "no effect" goes against the monster the line names
s, st, b, g, sent = new("Druid", 30)
kob, bsk = mon(s, "kobold thief"), mon(s, "blood skeleton")
sp = s.spellbook.find("quak") or next(iter(s.world.spells.values()))
s.spellbook.no_effect.clear()
s.spellbook.note_cast(kob, sp)
s.spellbook.feed_line("Your spell has no effect on blood skeleton.")
nums = {k[0] for k in s.spellbook.no_effect}
check(f"#4 stored against blood skeleton, not kobold thief ({s.spellbook.no_effect})",
      kob["num"] not in nums and any(m["name"] == "blood skeleton" for m in s.world.monsters.values()
                                     if m["num"] in nums))
s.spellbook.no_effect.clear()
s.spellbook.note_cast(kob, sp)
s.spellbook.feed_line("Your spell has no effect on kobold thief!")
check(f"#4 the cast-at monster named: still stored ({s.spellbook.no_effect})",
      (kob["num"], sp["Number"]) in s.spellbook.no_effect)

# 5. the multi spell: not cast at what it can't hurt, not resent when unknown
s, st, b, g, sent = new("Druid", 30)
rec = mon(s, "blood skeleton")
st.multi_spell = "swar"; st.auto_nuke = True; st.use_area_min = True; st.multi_min_mobs = 2
sw = s.spellbook.find("swar")
s.spellbook.no_effect.add((rec["num"], sw["Number"]))
mobs = [("blood skeleton", rec)] * 3
reset(b, g); sent.clear()
b.fight(mobs)
check(f"#5 swarm useless on blood skeletons: not cast ({sent})", not any(x.startswith("swar") for x in sent))
st.multi_spell = "xyzq"
reset(b, g); sent.clear()
for _ in range(3):
    b._cool = {}; b.fight(mobs)
check(f"#5 unknown multi spell never sent ({sent})", not any("xyzq" in x for x in sent))
s.spellbook.no_effect.clear()
st.multi_spell = "swar"
reset(b, g); sent.clear()
calls = []
real = s.spellbook.note_cast
s.spellbook.note_cast = lambda m, p: calls.append(p.get("Short")) or real(m, p)
kob = mon(s, "kobold thief")
b.fight([("kobold thief", kob)] * 3)
check(f"#5 a multi spell that goes out is noted ({sent}, {calls})",
      any(x.startswith("swar") for x in sent) and "swar" in calls)

# 6. PvP: heals still go out between rounds
s, st, b, g, sent = new(name="Evolution")
b.x.pvp_target = "Enemy"
g.view = RoomView("Arena", {"N"}, [], [], ["Enemy"], time.time())
b._cool["pvp_round"] = time.time()
b.ready("pvp_round", 5)
r = b.x.pvp_tick()
check(f"#6 between PvP rounds pvp_tick lets the heal tick run ({r})",
      r is False and getattr(b.x, "pvp_hold", 0) >= time.time() - 1)

# 7. attack last: a party member's heal isn't a fight starting
s, st, b, g, sent = new(name="Buddy")
st.attack_last = True
g.party = {"Buddy": {"hp": 100, "t": time.time()}, "Evolution": {"hp": 100, "t": time.time()}}
cw = {"name": "copsewight", "exp": 100, "hp": 40, "align": 1, "num": 3}
g.view = RoomView("Glade", {"N"}, [("copsewight", cw)], [], ["Evolution"], time.time())
g.in_combat = True
b._attack_cmd = ("a copsewight", time.time() - 3)
seen = []
b._attack_after_party = lambda nm: seen.append(nm)
b.note_line("Evolution casts cure poison on Buddy!")
check(f"#7 'casts cure poison on Buddy' isn't an attack ({seen})", not seen)
b.note_line("Evolution casts fireball at copsewight!")
check(f"#7 'casts fireball at copsewight' is ({seen})", seen == ["Evolution"])

# 9. area spells held while a monster we don't attack is here
s, st, b, g, sent = new()
g.party = {"Bob": {}}
st.attack_good = st.attack_neutral = False
guard = {"name": "town guard", "exp": 100, "hp": 100, "align": 0, "num": 4}
g.view = RoomView("Gate", {"N"}, [("orc", orc), ("town guard", guard)], [], [], time.time())
check(f"#9 a guard here: no area spells ({b.aoe_blocked()})", b.aoe_blocked() and "town guard" in b.aoe_blocked())
st.aoe_safety = False
check("#9 held even with AoE safety off", b.aoe_blocked())
st.aoe_safety = True
st.attack_good = True
check(f"#9 attacking good on: the guard's a target ({b.aoe_blocked()})", b.aoe_blocked() is None)
st.attack_good = False
st.ignore_mobs = ["orc"]
g.view = RoomView("Gate", {"N"}, [("orc", orc), ("kobold", {**orc, "name": "kobold"})], [], [], time.time())
check(f"#9 never-attack list monster here ({b.aoe_blocked()})", b.aoe_blocked() and "orc" in b.aoe_blocked())
st.ignore_mobs = []
check("#9 only targets here: area spells fine", b.aoe_blocked() is None)
st.pvp_realm = True
g.view = RoomView("Gate", {"N"}, [("orc", orc)], [], ["Stranger"], time.time())
check(f"#9 a stranger on a PvP realm still holds them ({b.aoe_blocked()})", b.aoe_blocked() and "Stranger" in b.aoe_blocked())

# 10. alone, the 'can't afford it, cast anyway' retry doesn't happen
s, st, b, g, sent = new("Mage", 30)
g.party = {}
avails = []
real_ap = s.spellbook.auto_pick
def ap(cands, recs, lvl, avail, *a, **k):
    avails.append(avail)
    return None if avail < 10 ** 6 else real_ap(cands, recs, lvl, avail, *a, **k)
s.spellbook.auto_pick = ap
from mudpilot.spells import spell_kind
area_sp = next(sp for sp in s.world.spells.values() if is_attack_spell(sp) and spell_kind(sp) not in (None, "single"))
b.s.spell_candidates = lambda: [x for x in [s.spellbook.find("mmis"), area_sp] if x]
s.spellbook.useless = lambda r, sp: spell_kind(sp) in (None, "single")     # only the area spell can hurt it
st.auto_nuke = True; st.use_area_min = True
g.ma = 5
rec = mon(s, "blood skeleton")
b._can_hit_fallback([("blood skeleton", rec)], rec, 0)
check(f"#10 solo: no 'any mana' retry ({avails})", 10 ** 6 not in avails)
avails.clear()
g.party = {"Bob": {}, "Ally": {}}
b._can_hit_fallback([("blood skeleton", rec)], rec, 0)
check(f"#10 with a party: the retry still happens ({avails})", 10 ** 6 in avails)

# 11. the game's level beats a stale setting
s, st, b, g, sent = new("Mage", 52)
st.char_level = 30
g.level = 52
mm = s.spellbook.find("mmis")
check("#11 level 52 in game, 30 in settings: magic missile is too low", s.spell_too_low(mm))

# 12. the stall watchdog sees the other melee verbs
s, st, b, g, sent = new()
for line in ("You slap the orc for 3 damage!", "You critically smash the orc for 40 damage!",
             "You surprise the orc for 12 damage!", "You jumpkick the orc for 9 damage!"):
    check(f"#12 own attack: {line}", b.OWN_ATTACK_RE.match(line))
check("#12 'You gain 100 experience' isn't an attack", not b.OWN_ATTACK_RE.match("You gain 100 experience."))

# F1 / F2: room tracking
s, st, b, g, sent = new()
w = s.world
pair = None
for k, r in w.rooms.items():
    if not r.name:
        continue
    shown = set(r.exits.keys())
    for d, ex in r.exits.items():
        r2 = w.room(ex.to)
        if r2 and ex.to != k and r2.name == r.name and w.match_room(ex.to, r.name, shown) and \
                w.match_room(k, r2.name, set(r2.exits.keys())):
            pair = (k, ex.to, shown)
            break
    if pair:
        break
if pair:
    a, c, shown = pair
    g.candidates = [a]
    g.pending.clear()
    g._locate(None, w.room(c).name, shown)
    check(f"F1 unsolicited look-alike display keeps the neighbour too ({g.candidates})", a in g.candidates and c in g.candidates)
    g.candidates = [a]
    g.pending.append(("look", None, [a]))
    g._locate(g.pending.popleft() if hasattr(g.pending, "popleft") else g.pending.pop(0), w.room(a).name, shown)
    check(f"F1 a look we asked for still means 'stayed' ({g.candidates})", g.candidates == [a])
else:
    check("F1 found a look-alike pair to test with", False)
g.pending.append(("move", "N", [(1, 1)]))
g._scan_misc("You are dead!")
check(f"F2 death clears the queued moves ({list(g.pending)})", not g.pending)

print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
