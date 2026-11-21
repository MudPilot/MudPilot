"""0.8.187 (Dan, 2026-11-12): "i dont think revolution pve is using the emerald-tipped crozier as a bless like he
should". Two things were wrong on PVEREV (priest, weapon in hand, golden chalice off-hand):
  * the bless did 'eq emerald-tipped crozier' straight away: "You may not ready a 2-handed weapon with your golden
    chalice worn!", then 'use crozier' failed — every 8 minutes, all day. Now it's the '#etc' swap: chalice off,
    crozier on, use it, weapon and chalice back on.
  * it had learned "You are no longer following Evolution." as divine intervention's wear-off line (any line with
    "no longer" was a candidate). Party/follow lines are never learned now, and ones already learned are forgotten."""
import os, sys
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"; st.char_class = "Priest"; st.char_level = 55
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
s.log = lambda m, *a, **k: None
sent = []
class Tel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): pass
s.telnet = Tel(); s._entered = True
b, x = s.bot, s.bot.x
b.log = lambda m, *a, **k: None
rule = {"name": "divine intervention (emerald-tipped crozier)", "cast": "use crozier", "every": 0, "enabled": True,
        "op": ">=", "value": 0, "equip_cmd": "eq emerald-tipped crozier",
        "off_msg": "You are no longer following Evolution.", "off_msg_learned": True,
        "_on_candidate": "-- Following your Party leader southeast --"}
st.buffs = [rule]; st.auto_bless = True; st.bless_st_timers = False; st.abil_check_cmd = ""
s.state.carrying = ("silvery mace (Weapon Hand), golden chalice (Off-Hand), emerald-tipped crozier, 2 rations")

n = x._drop_bad_learned()
check(f"the follow line learned as its wear-off is forgotten ({n})", n == 1 and not rule.get("off_msg")
      and "off_msg_learned" not in rule and "_on_candidate" not in rule)
x._learn_off("You are no longer following Evolution.")
check("…and isn't learned again", not rule.get("off_msg"))

b.buff_status = lambda r: (True, "due")
b.may_cast = lambda: True
sent.clear()
b.buffs_tick([], False)
c = [l for l in sent if l.strip()]
check(f"chalice off, crozier on, use it, mace and chalice back ({c})", c == [
    "remove golden chalice", "eq emerald-tipped crozier", "use emerald-tipped crozier",
    "eq silvery mace", "eq golden chalice"])

s.state.carrying = "emerald-tipped crozier (Weapon Hand), golden chalice, 2 rations"
b._buff_cast.clear(); sent.clear()
b.buffs_tick([], False)
c = [l for l in sent if l.strip()]
check(f"already holding the crozier: just use it ({c})", c == ["use emerald-tipped crozier"])

s.state.carrying = ""
b._buff_cast.clear(); sent.clear()
b.buffs_tick([], False)
check(f"pack not read yet (just logged in): waits instead of guessing ({sent})", not [l for l in sent if l.strip()])

s.state.carrying = "silvery mace (Weapon Hand), 2 rations"
b._buff_cast.clear(); sent.clear()
b.buffs_tick([], False)
c = [l for l in sent if l.strip()]
check(f"not carrying it: the plain equip / use / weapon back as before ({c})",
      c[:2] == ["eq emerald-tipped crozier", "use crozier"])
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
