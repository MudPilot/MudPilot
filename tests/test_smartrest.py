"""Smart resting (Dan, 2026-11-18): rest vs meditate + greater mend vs rgen + meditate, on the character's own rates."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
from mudpilot.smartrest import spell_avg, spell_rounds
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
st.heal_cmd, st.hp_regen_cmd, st.meditate_cmd = "grme", "rgen", "medi"
st.rest_below_hp, st.rest_until_hp, st.rest_below_ma, st.rest_until_ma = 80, 90, 70, 90
st.auto_heal, st.heal_pct, st.char_level = True, 90, 52
s = Session(st); s._no_log_file = True
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
b, gs = s.bot, s.state
b.send = lambda c, *a, **k: sent.append(c)
gs.level, gs.max_hp, gs.max_ma = 52, 932, 458
sm = b.smart
gm = s.spellbook.find("grme")
check(f"greater mend from the spell data: 25-45 → avg {spell_avg(gm, 52)}", spell_avg(gm, 52) == 35)
rg = s.spellbook.find("rgen")
check(f"rgen lasts {spell_rounds(rg, 52)} rounds", spell_rounds(rg, 52) >= 20)
# nothing learned → nothing changes
check("no rates yet → None (usual rules)", sm.next_action(400, 932, 400, 458, 90, 90) is None)
# learn from rests (Revolution's measured: meditate 0.64 HP/s 3.83 MA/s, rest 2.07 / 3.13)
for _ in range(4):
    sm.learn_rest({"kind": "meditate", "secs": 100, "breaks": 0, "ended": "topped up",
                   "start": {"hp": 50, "ma": 10}, "end": {"hp": 50 + 64 * 100 / 932, "ma": 10 + 383 * 100 / 458}}, 932, 458)
    sm.learn_rest({"kind": "rest", "secs": 100, "breaks": 0, "ended": "topped up",
                   "start": {"hp": 50, "ma": 10}, "end": {"hp": 50 + 207 * 100 / 932, "ma": 10 + 313 * 100 / 458}}, 932, 458)
r = st.smart_rest_rates
check(f"learned meditate {r['med_hp']:.2f} HP/s {r['med_ma']:.2f} MA/s", abs(r["med_hp"] - .64) < .02 and abs(r["med_ma"] - 3.83) < .03)
sm.learn_rest({"kind": "rest", "secs": 10, "breaks": 0, "ended": "x", "start": {"hp": 1, "ma": 1}, "end": {"hp": 90, "ma": 90}}, 932, 458)
sm.learn_rest({"kind": "rest", "secs": 90, "breaks": 2, "ended": "x", "start": {"hp": 1, "ma": 1}, "end": {"hp": 90, "ma": 90}}, 932, 458)
check("short / interrupted rests aren't learned", r["rest_hp_n"] == 4)
# heal size from the game's own line
for n in (43, 40, 25, 41, 30):
    b.note_line("You cast greater mend on Revolution, healing %d damage!" % n)
check(f"heal size learned ({r.get('heal', 0):.1f})", r.get("heal_n") == 5 and 30 < r["heal"] < 42)
b.note_line("You cast greater mend on Miserable, healing 45 damage!")
check("healing someone else isn't learned", r.get("heal_n") == 5)
# the plans (as worked out for Dan)
def act(hp, ma):
    sm._cache = None
    return sm.next_action(hp * 932 // 100, 932, ma * 458 // 100, 458, 90, 90), sm.last_plan
a, p = act(40, 90)
check(f"HP 40% MA 90% → heal first ({p['name']}, {p['secs']:.0f}s vs rest {p['rest_secs']:.0f}s)", a == "heal")
a, p = act(40, 40)
check(f"HP 40% MA 40% → heals then rgen ({p['name']} {p['heals']} heals {p['rgens']} rgen)", a == "heal" and p["rgens"] >= 1)
a, p = act(78, 42)
check(f"HP 78% MA 42% → rgen + meditate ({p['name']}, {p['secs']:.0f}s vs {p['rest_secs']:.0f}s)", a == "rgen")
sm.cast_rgen()
sm._cache = None
a, p = act(78, 42)
check(f"…rgen running → meditate ({a}, {p['name']})", a == "meditate")
sm._rgen_until = 0
a, p = act(85, 95)
check(f"mana fine, HP 85% → a heal or two ({a}, {p['name']})", a in ("heal", "meditate", "rgen"))
# should_rest acts on it (switch on)
st.smart_rest = True
sm._cache = None
gs.hp, gs.ma, gs.resting, gs.in_combat = 400, 420, False, False
gs.view = None
b._last_spell_at = 0; b._cool.clear(); sent.clear()
b.should_rest([], False)
check(f"should_rest: HP 43% MA 92% → casts grme ({sent})", "grme" in sent)
st.smart_rest = False
sent.clear(); b._cool.clear(); b._last_spell_at = 0
b.should_rest([], False)
check(f"switch off → the usual rest ({sent})", "grme" not in sent and "rest" in sent)
# heal_tick defers an over-the-line self heal when the plan says meditate
st.smart_rest = True
gs.hp, gs.ma = 760, 190        # 81% HP, 41% mana: mana's the slow part
sm._rgen_until = time.time() + 60
sm._cache = None; sent.clear(); b._cool.clear(); b._last_spell_at = 0
b.heal_tick()
check(f"heal_tick: HP 81% with mana short and rgen running → no grme ({sent})", "grme" not in sent)
gs.hp = 300                    # 32%: under the safety line — heal now
sent.clear(); b._cool.clear(); b._last_spell_at = 0
b.heal_tick()
check(f"heal_tick: under {st.smart_rest_safe_hp}% → grme whatever the plan ({sent})", "grme" in sent)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
