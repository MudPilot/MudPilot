"""Monster attack simulator (port of MME clsMonsterAttackSim) — sanity + hand-checked formulas.

Imports the stock MME data file into a scratch db (never touches data/ or bundled/).
Run: python3.12 tests/test_monattack.py
"""
import os, sys, tempfile, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot.worlddb import WorldDB
from mudpilot.monattack import simulate, build_sim, MonsterAttackSim, gmud_diminishing_returns

MDB = os.environ.get("MME_MDB", "/tmp/mmud-explorer/data-v1.11p.mdb")
if not os.path.exists(MDB):
    print("SKIP: no MME data file at", MDB)
    sys.exit(0)

scratch = tempfile.mkdtemp(prefix="monattack-")
db_path = os.path.join(scratch, "stock.db")
t0 = time.time()
w = WorldDB.import_mdb(MDB, db_path)
print(f"imported {len(w.monsters)} monsters in {time.time() - t0:.1f}s")
assert all("attack_data" in m for m in w.monsters.values())


def by_name(name):
    m = w.boss_named(name)
    assert m, name
    return m["num"]


# ---- 1. weak monster: giant rat (AC 0 -> 99% hit cap, bite 2-10, 1 attack/round)
rat = by_name("giant rat")
r = simulate(w, rat, {}, rounds=2000, seed=1)
print("giant rat:", r["avg"], "max seen/possible", r["max_round_seen"], r["max_possible"], r["attacks"][0]["name"])
assert r["avg"] > 0 and r["max_possible"] >= r["max_round_seen"] and r["max_possible"] == 10
assert abs(r["avg"] - 6 * 0.99) < 0.4
assert simulate(w, rat, {}, rounds=2000, seed=1) == r, "not deterministic with a seed"

# ---- 2. hand-checked formulas on slime beast (acc 85, 9-30, 1000 energy/attack)
slime = by_name("slime beast")
# AC 40: hit% = Round(1 - ((40^2)/100) / ((85^2)/140), 2) * 100 = 69 ; DR 5 -> avg 14.5 per hit
exp = 0.69 * 14.5
r = simulate(w, slime, {"ac": 40, "dr": 5}, rounds=100000, seed=2)
print(f"slime beast AC40/DR5: {r['avg']} (hand calc {exp:.3f})")
assert abs(r["avg"] - exp) < 0.15
# + dodge 20 stock: Fix((20*10)/(85/8)) = 18% dodge after the AC check
exp = 0.69 * 0.82 * 14.5
r = simulate(w, slime, {"ac": 40, "dr": 5, "dodge": 20}, rounds=100000, seed=2)
print(f"  + dodge 20: {r['avg']} (hand calc {exp:.3f})")
assert abs(r["avg"] - exp) < 0.15
# GreaterMUD: hit cap 100, dodge = CLng(20^2 / ((85^2/14)/10)) = 8%
exp = 0.69 * 0.92 * 14.5
r = simulate(w, slime, {"ac": 40, "dr": 5, "dodge": 20}, rounds=100000, seed=2, greatermud=True)
print(f"  GMUD: {r['avg']} (hand calc {exp:.3f})")
assert abs(r["avg"] - exp) < 0.15
# GMUD diminishing returns: triangular-number inverse, DR(4*t(t+1)/2, 4) == 4*t
assert abs(gmud_diminishing_returns(4 * 10 * 11 / 2, 4.0) - 40) < 1e-9

# ---- 3. MR / damage-resist formulas (CalcResistedDamage)
crd = MonsterAttackSim.calc_resisted_damage
assert crd(100, 50, 0) == 100 and crd(100, 150, 0) == 50 and crd(100, 30, 0) == 120
assert crd(100, 100, 1) == 50 and crd(100, 200, 1) == 25

# ---- 4. a strong boss with spell attacks + between-round spells
for boss_name in ("Majestic Dragon", "Demon Lord"):
    boss = by_name(boss_name)
    t = time.time()
    base = simulate(w, boss, {}, rounds=2000, seed=3)
    dt = time.time() - t
    armored = simulate(w, boss, {"ac": 120, "dr": 30, "dodge": 40}, rounds=2000, seed=3)
    resist = simulate(w, boss, {"mr": 150, "antimagic": True, "rfir": 50, "rcol": 50, "rlit": 50,
                                "rsto": 50, "rwat": 50}, rounds=2000, seed=3)
    print(f"{boss_name}: avg {base['avg']} (phys {base['phys_avg']} / spell {base['spell_avg']}) "
          f"max {base['max_round_seen']}/{base['max_possible']}  MME AvgDmg {base['mme_avg']}  [{dt * 1000:.0f} ms]")
    for a in base["attacks"]:
        print(f"    {a['kind']:7} {a['name'][:28]:28} used {a['used_pct']:5}%  hit {a['hit_pct']:5}%  "
              f"avg {a['avg_hit']:6}  resisted {a['resisted_pct']:5}%")
    print(f"  armored (AC120/DR30/dodge40): {armored['avg']}   high MR+antimagic+resists: {resist['avg']}")
    assert base["avg"] > 0 and base["max_possible"] >= base["max_round_seen"] > 0
    assert armored["phys_avg"] < base["phys_avg"], "more AC/DR/dodge must reduce physical damage"
    assert resist["spell_avg"] < base["spell_avg"], "MR/resists must reduce spell damage"
    assert abs(base["avg"] - base["mme_avg"]) <= max(1.0, 0.06 * base["mme_avg"]), "far from MME's AvgDmg"
    assert dt < 1.0

# ---- 5. monotonic in AC for a physical monster
orc = by_name("elite orc guard")
avgs = [simulate(w, orc, {"ac": ac}, rounds=4000, seed=4)["avg"] for ac in (0, 20, 40, 60, 80)]
print("elite orc guard avg by AC 0/20/40/60/80:", avgs)
assert all(a > b for a, b in zip(avgs, avgs[1:]))

# ---- 6. whole-realm comparison against MME's precomputed AvgDmg (stock settings: AC0, MR50)
t = time.time()
close = 0
for num in w.monsters:
    ref = w.monsters[num]["attack_data"]["mme_avg"]
    got = simulate(w, num, {}, rounds=2000, seed=num)["avg"]
    close += abs(got - ref) <= max(0.6, 0.06 * ref)
print(f"{close}/{len(w.monsters)} monsters within 6% of MME AvgDmg ({time.time() - t:.1f}s)")
assert close >= 0.98 * len(w.monsters)

# ---- 7. old world.db without attack data -> None
import sqlite3
con = sqlite3.connect(db_path)
con.execute("UPDATE monsters SET atk=NULL")
con.commit(); con.close()
w_old = WorldDB(db_path)
assert "attack_data" not in w_old.monsters[rat] and simulate(w_old, rat, {}) is None
assert simulate(w, 999999, {}) is None

import shutil
shutil.rmtree(scratch, ignore_errors=True)
print("ALL PASS")
