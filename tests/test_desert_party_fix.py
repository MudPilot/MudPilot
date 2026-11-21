"""Buddy leading into the Scorching Desert, 2026-11-04 — three things went wrong:
1. 'use waterskin' went out as 'use Windblade' ('#w' is Windblade's shortcut), so nobody drank — Dan did it by hand.
2. Revolution wears the sunstone wristband, but only '@have waterskin' was asked, so one was bought for him.
3. The walk to the shop for it asked the party again, which replaced the errand: 'then on to 12/49 Village Store'
   — it got there, handed the waterskin over and stopped dead."""
import os, sys, time
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, here)
os.environ["MUDPILOT_NO_RECORD"] = "1"
from types import SimpleNamespace
from mudpilot import config
from mudpilot.session import Session
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
st = config.Settings(); st.save = lambda: None; st.my_name = "Buddy"
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
w, b, e, g = s.world, s.bot, s.bot.errands, s.state
SKIN, BAND = w.item_names["waterskin"]["num"], w.item_names["sunstone wristband"]["num"]
# 1. the item-spell shortcut only when it's really that item's
out = []
class T:
    connected = True
    def send_line(self, x): out.append(x)
s.telnet = T()
g.carrying = "waterskin, Windblade (Weapon Hand), mithril helm (Head)"
s.send("use waterskin", from_bot=True)
check(f"'use waterskin' goes out as itself ({out})", out and out[-1] == "use waterskin")
# 2. ask about the wristband too; wearing it is as good as a waterskin
sent = []
s.send = lambda c, from_bot=False: sent.append(c)
g.party = {"Buddy": {}, "Revolution": {}, "Evolution": {}}
s.comeback.leading = lambda: True
mp = SimpleNamespace(title="Go to 12/1192 Small Pyramid, Seeress's Den", steps=[])
carry = [frozenset({SKIN, BAND})]
check("asks the party", e.party_check(mp, False, carry))
check(f"…about the waterskin and the sunstone wristband ({sent})",
      "/Revolution @have waterskin" in sent and "/Revolution @have sunstone wristband" in sent)
for who, body in (("Revolution", "{no waterskin}"), ("Revolution", "{yes: sunstone wristband}"),
                  ("Evolution", "{yes: 3 waterskin}"), ("Evolution", "{no sunstone wristband}")):
    e.have_answer(who, body)
walked = []
b.start_path = lambda p, l=None, checked=False, **k: walked.append(p.title)
logs = []
b.log = lambda m, *a, **k: logs.append(m)
e._asking_tick()
check(f"wristband on Revolution, waterskin on Evolution: nothing to buy, walks on ({logs[-1:]})",
      walked == [mp.title] and not e.active)
# …and one with neither still gets a waterskin bought
sent.clear(); walked.clear(); e._rounds = {}
e.party_check(mp, False, carry)
for who, body in (("Revolution", "{no waterskin}"), ("Revolution", "{no sunstone wristband}"),
                  ("Evolution", "{yes: waterskin}"), ("Evolution", "{no sunstone wristband}")):
    e.have_answer(who, body)
b.set_mode = lambda *a, **k: None
e._asking_tick()
check(f"neither: buys him a waterskin ({logs[-2:]})", e.active and e.active["todo"][0]["num"] == SKIN
      and e.active["todo"][0]["for"] == "Revolution" and e.active["then"][0] is mp)
# 3. the errand's walk to the shop doesn't ask again (and so doesn't replace the errand)
sent.clear()
called = []
real = e.party_check
e.party_check = lambda *a, **k: called.append(a) or real(*a, **k)
b.carry_sets = lambda p: carry
del b.start_path
from mudpilot.megamud_files import MPath
shop = MPath(name="Go to 12/49 Village Store", author="", start_hash="a", end_hash="b")
shop.resolved = True
b.missing_items = lambda p: ([], [])
b.path_toll = lambda p: 0
def walk():
    try:
        b.start_path(shop, False)
    except Exception:
        pass                                         # (the walk itself needs a live game — only the check matters)
keep, e.active = e.active, None
walk()
check("(control: without an errand under way, the same walk does ask)", called)
called.clear(); sent.clear(); e.asking = None; e._rounds = {}
e.active = keep
walk()
check(f"on the errand's walk: no second @have round ({sent})", not called and not any("@have" in c for c in sent))
check("…the errand still goes on to the Seeress's Den afterwards", e.active and e.active["then"][0] is mp)
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
