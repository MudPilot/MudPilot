"""Bash and smash in the weapon calculator (MME CalculateAttack, stock rules)."""
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from mudpilot import gearcalc as G

f = G.Fighter(level=41, combat=4, agility=80, strength=155, encum_pct=51)
dai = {"name": "daikatana", "abils": {58: 4}, "Speed": 1950, "Min": 12, "Max": 36, "StrReq": 70, "Accy": 4}
scy = {"name": "wicked bone scythe", "abils": {}, "Speed": 4400, "Min": 20, "Max": 65, "StrReq": 90, "Accy": 0}

n = G.weapon_round(dai, f)
b = G.weapon_round(dai, f, attack="bash")
s = G.weapon_round(dai, f, attack="smash")
assert n.swings == 5 and n.crit_pct == 14, n
assert b.crit_pct == 0 and b.energy == n.energy * 2, b              # bash: double energy, no crits
assert b.avg_hit == round((int(12 * 1.1) * 3 + int(36 * 1.1) * 3) / 2), b
assert s.swings == 1 and s.crit_pct == 0 and s.avg_hit == round((int(12 * 1.2) * 5 + int(36 * 1.2) * 5) / 2), s
assert b.round_dmg > n.round_dmg > s.round_dmg, (n.round_dmg, b.round_dmg, s.round_dmg)

# the slow scythe smashes best
ns, bs, ss = (G.weapon_round(scy, f, attack=k).round_dmg for k in G.ATTACKS)
assert ss > bs > ns, (ns, bs, ss)
assert ss == 255, ss

# DR comes off before the multiplier
d10 = G.weapon_round(scy, f, {"dr": 10}, attack="smash")
assert d10.avg_hit == round((max(int(20 * 1.2) - 10, 0) * 5 + (int(65 * 1.2) - 10) * 5) / 2), d10

# accuracy penalty: smash hits less than normal against armour
mon = {"ac": 60, "dr": 0, "abils": {}}
fa = G.Fighter(level=41, combat=4, agility=80, strength=155, encum_pct=51, accuracy=90)
assert G.weapon_round(scy, fa, mon, "smash").hit_pct < G.weapon_round(scy, fa, mon).hit_pct

assert G.attack_kind("bash {target}") == "bash" and G.attack_kind("sm {target}") == "smash"
assert G.attack_kind("a {target}") == "normal" and G.attack_kind("") == "normal"
print("bash/smash ok")
