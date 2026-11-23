"""0.8.208 (Dan, 2026-11-19): the leader doesn't wait on the mana of a member whose own 'Rest below MA' is 0 (Buddy, a
melee Paladin); and waiting already rested, the rest gear isn't swapped on and off every 6 s."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
st.party_wait_pct, st.party_wait_ma_pct, st.party_wait_ma_until = 50, 20, 60
s = Session(st); s._no_log_file = True
b, g, x = s.bot, s.state, s.bot.x
sent = []
b.send = sent.append; x.send = sent.append
x.leading = lambda: True
now = time.time()
g.party = {"Miserable": {"hp": 100, "ma": 100, "t": now}, "Buddy": {"hp": 100, "ma": 5, "t": now}}
s.partysync.info = lambda: {"Buddy": {"rma": 0}}
check(f"Buddy at 5% mana, his rest-mana line 0: no wait ({x.waiting_on})", not x.wait_for_party())
s.partysync.info = lambda: {"Buddy": {"rma": 40}}
check(f"…with a rest-mana line of 40: waits ({x.waiting_on})", x.wait_for_party())
x.waiting_on = []
s.partysync.info = lambda: {}
check("…an older MudPilot (no line sent): waits, as before", x.wait_for_party())
print("my info carries the line:", s.partysync.my_info() if g.max_ma else "(no max ma)")
g.max_ma, g.ma = 400, 380
st.rest_below_ma = 0
check(f"my own line goes out ({s.partysync.my_info()})", "rma=0" in s.partysync.my_info())
# idle rest, already over 'rest until': no gear swap
st.auto_rest, st.rest_until_hp, st.rest_until_ma = True, 90, 90
st.auto_regen_gear = False; st.rest_swap_on = True; st.pre_rest_cmd = "eq runed cape"; st.post_rest_cmd = "eq shawl"
g.max_hp, g.hp = 900, 880; g.resting = False; g.in_combat = False
sent.clear(); b._cool.pop("idle_regen", None)
b.idle_regen([])
check(f"waiting, over 'rest until': rests in what's on ({sent})", "eq runed cape" not in sent and b._swap is None)
g.hp = 500; sent.clear(); b._cool.pop("idle_regen", None)
b.idle_regen([])
check(f"0.8.224 (Dan): waiting and actually short: still no gear swap for a party-wait rest ({sent})",
      "eq runed cape" not in sent and "rest" in sent)
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
