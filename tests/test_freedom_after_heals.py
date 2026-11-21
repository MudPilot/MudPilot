"""Dan, 2026-11-16: Revolution cast freedom on Miserable (knocked off his feet) and then sat healing for 3-4 rounds anyway.
Heals and rest first; if a member is still down once the party's healed up and ready to move, then free them."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.gamestate import RoomView
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)

st = config.Settings(); st.save = lambda: None; st.my_name = "Revolution"
st.freedom_cmd = "free"; st.party_heal = True; st.party_heal_pct = 70; st.heal_pct = 50; st.rest_below_hp = 60
s = Session(st); s._no_log_file = True
b, g, x = s.bot, s.state, s.bot.x
sent = []
b.send = sent.append; x.send = sent.append
x._is_spell = lambda cmd: True
b.slot_free = lambda: True
care = x.care
g.max_hp, g.hp = 900, 880
g.resting = False
g.view = RoomView("Bristlewood Grove", {"E"}, players=["Miserable"])

def party(hp):
    g.party = {"Revolution": {"hp": 98, "t": time.time()}, "Miserable": {"hp": hp, "t": time.time()}}

party(40)
care.cond = {"Miserable": {"held": time.time()}}
sent.clear()
check(f"Miserable at 40% and held: no freedom yet ({sent})", not care.tick() and not sent)
g.resting = True; party(90)
sent.clear()
check(f"party healed but we're resting: still waiting ({sent})", not care.tick() and not sent)
g.resting = False; g.hp = 400
sent.clear()
check(f"I'm hurt (44%): heal / rest first ({sent})", not care.tick() and not sent)
g.hp = 880; party(90)
sent.clear()
check(f"everyone healed, ready to move, still down: free him ({sent})", care.tick() and sent == ["free Miserable"])
# 0.8.208 (Dan, 2026-11-19): the 'par' from before the knockdown said 97% — wait for one after it
care._tried.clear(); care._tries.clear()
party(97)
care.cond = {"Miserable": {"held": time.time() + 0.01}}
sent.clear()
check(f"held just now, last par from before the hit: wait ({sent})", not care.tick() and not sent)
time.sleep(0.02); party(95)
sent.clear()
check(f"…a par after the report, still 95%: free him ({sent})", care.tick() and sent == ["free Miserable"])
# about to sit for mana anyway (Revolution at 67%, rest line 70%)
care._tried.clear(); care._tries.clear()
st.rest_below_ma = 70; g.max_ma, g.ma = 458, 307
care.cond = {"Miserable": {"held": time.time() - 1}}; party(95)
sent.clear()
check(f"under the mana rest line: no freedom yet ({sent})", not care.tick() and not sent)
g.ma = 440
sent.clear()
check(f"mana fine: free him ({sent})", care.tick() and sent == ["free Miserable"])
st.rest_below_ma = 0
# poison isn't held back (it keeps hurting)
care.cond = {"Miserable": {"poison": time.time()}}; party(40); st.cure_poison_cmd = "cure"
care._tried.clear(); care._tries.clear(); sent.clear()
check(f"poison still cured straight away ({sent})", care.tick() and sent == ["cure Miserable"])
# myself held, in a party: the same
x.ailments = {"held": time.time()}
care.cond = {}
g.resting = True; sent.clear(); b._cool.clear()
check(f"I'm held while the party rests: no self-freedom ({sent})", not x.cure_tick() and "free" not in sent)
g.resting = False; party(95); sent.clear(); b._cool.clear()
check(f"rest done: free myself ({sent})", x.cure_tick() and "free" in sent)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
