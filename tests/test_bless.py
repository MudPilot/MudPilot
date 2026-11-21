"""Self blesses fire on a timer (MME duration − margin, any cast form); party blesses fire in a party."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.gamestate import RoomView
st = config.Settings(); st.save = lambda: None; st.auto_spells = False; st.auto_combat = False
st.buffs = [{"name": "bless", "cast": "cast bles", "every": 0, "enabled": True, "op": ">=", "value": 0},
            {"name": "x", "cast": "zzzz", "every": 0, "enabled": True, "op": ">=", "value": 0}]
st.party_blesses = [{"cast": "prot {name}", "secs": 0, "enabled": True}]
s = Session(st); b = s.bot
sent = []
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = T(); s._want_connected = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
s.state.max_hp = s.state.hp = 500; s.state.max_ma = s.state.ma = 300
s.state.view = RoomView("Town", {"N"}); s.state.view.t = time.time() + 999
sp = b.spell_for_cast("cast bles")
check(f"'cast bles' finds the spell ({sp and sp.get('Name')})", sp is not None)
def ticks(n=12):
    for _ in range(n):
        b._cool = {"par": time.time(), "par_solo": time.time()}; b._last_spell_at = 0; b.tick()
sent.clear(); ticks()
check(f"self blesses cast ({sent})", "cast bles" in sent and "zzzz" in sent)
sent.clear(); ticks()
check("not recast straight away", "cast bles" not in sent)
s.state.party = {"Tester": {"hp": 100}, "Lyra": {"hp": 100}}
st.my_name = "Tester"
sent.clear(); ticks()
check(f"party bless each member ({sent})", "prot Lyra" in sent and "prot Tester" not in sent)
# stat shows "You feel armoured! (111s)": recast at the margin, not before
st.buffs[0]["on_msg"] = "You feel armoured!"
b.x._sync_bless("you feel armoured!", 111)
need, why = b.buff_status(st.buffs[0])
check(f"synced from stat: not due yet ({why})", not need)
b.x._sync_bless("you feel armoured!", 10)
need, why = b.buff_status(st.buffs[0])
check(f"under the margin: due ({why})", need)
# an item's spell: wield the crozier, cast, wield your weapon again
st.buffs = [{"name": "crozier", "cast": "use crozier", "every": 0, "enabled": True, "op": ">=", "value": 0,
             "equip_cmd": "eq emerald-tipped crozier"}]
s.state.carrying = "vortex staff (Weapon Hand), rope and grapple"
b._buff_cast.clear(); sent.clear(); ticks(2)
check(f"swap in, use, swap back ({sent})", sent[:3] == ["eq emerald-tipped crozier", "use crozier", "eq vortex staff"])
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
