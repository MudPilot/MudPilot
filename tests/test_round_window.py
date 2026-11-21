"""Mid-fight blesses and heals go out just after a round fires (then the attack is re-armed), never late in a
round; a major heal doesn't wait."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st)
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T()
s.bot.send = lambda c: sent.append(c)
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
b, g, clock = s.bot, s.state, s.clock
clock.period, clock.learned = 5.0, True
def round_ago(secs):
    clock.last_round = clock.last_line = time.time() - secs

round_ago(0.4)
check("0.4 s after a round is the window", b.just_after_round())
round_ago(3.0)
check("3 s after (2 s to go) still is", b.just_after_round())
round_ago(3.8)
check("1.2 s before the next round isn't (late-cast guard)", not b.just_after_round())
clock.last_round = 0
check("no round seen yet isn't", not b.just_after_round())

# blesses
st.buffs = [{"name": "mshi", "cast": "mshi", "enabled": True}]
b.buff_status = lambda bf: (True, "due")
b.may_cast = lambda gap=None: True
mobs = [("nightshade", {"name": "nightshade"})]
g.in_combat = True
round_ago(3.8); sent.clear(); b._buff_cast.clear()
check("mid-fight bless waits when the next round is close", not b.buffs_tick(mobs, True) and "mshi" not in sent)
round_ago(0.3); b._cool["cast"] = time.time()
check("…and goes just after the round", b.buffs_tick(mobs, True) and "mshi" in sent)
check("…with the attack re-armed straight away", b._cool.get("cast") == 0)
# Evolution, 2026-11-01: the bless stopped the repeating attack — "no attack of ours for 8–15 s" — send it back
b._attack_cmd = ("vine sentry", time.time()); round_ago(0.3); sent.clear(); b._buff_cast.clear()
b.buffs_tick(mobs, True)
check(f"…and the attack sent again right after the bless ({sent})", sent[-2:] == ["mshi", "vine sentry"])
g.in_combat = False; st.auto_combat = True; b._buff_cast.clear(); sent.clear()
check("monsters here but no fight yet: attack first", not b.buffs_tick(mobs, True))

# heals
st.auto_heal = True
st.heal_cmd, st.heal_pct = "minor", 70
st.major_heal_cmd, st.major_heal_pct = "major", 30
g.max_hp, g.hp = 100, 50
g.in_combat = True
round_ago(3.8); sent.clear(); b._cool.pop("heal", None)
check("minor heal waits when the next round is close", not b.heal_tick() and "minor" not in sent)
round_ago(0.5); b._cool["cast"] = time.time()
check("…then heals", b.heal_tick() and "minor" in sent and b._cool.get("cast") == 0)
g.hp = 20; round_ago(3.8); sent.clear(); b._cool.pop("heal", None)
check("a major heal goes at once", b.heal_tick() and "major" in sent)
# Dan, 2026-10-30: heals only in the first 2.5 s of the round, and the attack straight back after it
g.hp = 50; round_ago(2.8); sent.clear(); b._cool.pop("heal", None)
check(f"2.8 s into the round: too late for a heal ({sent})", not b.heal_tick() and "minor" not in sent)
st.major_heal_pct = 60
g.hp = 45; round_ago(3.0); sent.clear(); b._cool.pop("heal", None)
check(f"a major heal that isn't life-or-death waits too ({sent})", not b.heal_tick() and "major" not in sent)
st.major_heal_pct = 30
b._attack_cmd = ("srip dragon", time.time())
g.hp = 50; round_ago(0.5); sent.clear(); b._cool.pop("heal", None)
check(f"heal, then the attack straight back ({sent})", b.heal_tick() and sent[-2:] == ["minor", "srip dragon"])
g.in_combat = False; g.hp = 50; sent.clear(); b._cool.pop("heal", None)
check("out of a fight heals don't wait", b.heal_tick() and "minor" in sent)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
