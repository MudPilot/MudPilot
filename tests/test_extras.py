"""Spells tab, bless timing + messages, party heals/bless, PvP spells, path building."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
from mudpilot.ansi import Style
from mudpilot.megamud_files import path_from_route
st = config.Settings(); st.save = lambda: None
st.my_name = "Tester"; st.auto_spells = False; st.auto_combat = False; st.char_level = 45
s = Session(st)
sent = []
class FakeTel:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): sent.append(x)
    def close(self): self.connected = False
s.telnet = FakeTel(); s._want_connected = True
feed = lambda *ls: [s._line([(l, Style())]) for l in ls]
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
def tick(n=1):
    for _ in range(n):
        s.bot._cool = {k: v for k, v in s.bot._cool.items() if k.startswith("par")}
        s.bot._last_spell_at = 0          # tests skip the one-spell-per-round wait
        s.bot._cool.setdefault("par", time.time()); s.bot._cool.setdefault("par_solo", time.time())
        s.bot.tick()
feed("[HP=600/MA=300]:Town Gates", "Obvious exits: north, south")
s.state.max_hp, s.state.hp, s.state.max_ma, s.state.ma = 600, 600, 300, 300
# --- major / minor self heal
st.auto_heal = True; st.heal_cmd = "mihe"; st.heal_pct = 70; st.major_heal_cmd = "mahe"; st.major_heal_pct = 40
s.state.hp = 200; sent.clear(); tick()
check("major heal below major %", "mahe" in sent)
s.state.hp = 360; sent.clear(); tick()
check("minor heal between", "mihe" in sent)
s.state.hp = 600
# --- cures
st.cure_poison_cmd = "cure"; feed("You have been poisoned!")
sent.clear(); tick()
check("cure poison", "cure" in sent)
feed("You are no longer poisoned."); sent.clear(); tick()
check("stops when cured", "cure" not in sent)
st.ignore_poison = True; feed("You have been poisoned!"); sent.clear(); tick()
check("ignore poison", "cure" not in sent)
st.ignore_poison = False; feed("You feel better.")
# --- bless timing from MME duration
st.auto_bless = True; st.bless_st_timers = False   # this board never answers st
st.buffs = [{"name": "Blur", "cast": "blur", "enabled": True}]
rec = s.bot.auto_recast(st.buffs[0])
check(f"blur recast = 210s - 15 = 195 (got {rec})", rec == 195)
sent.clear(); tick()
check("casts blur when never cast", "blur" in sent)
feed("You cast blur!", "Your image becomes blurry and hard to see.")
s.bot._buff_cast["blur"] -= 400; s.bot._buff_off["blur"] = True; sent.clear(); tick()
feed("You cast blur!", "Your image becomes blurry and hard to see.")
check("learned start message", st.buffs[0].get("on_msg") == "Your image becomes blurry and hard to see.")
sent.clear(); tick()
check("doesn't recast while active", "blur" not in sent)
s.bot._buff_cast["blur"] -= 150      # 150 s later (over half of 210)
# (0.8.108: the end line comes from the Messages file — blur's is "The effects of blur wear off")
feed("The effects of blur wear off!")
check(f"wear-off message from the Messages file ({st.buffs[0].get('off_msg')!r})",
      (st.buffs[0].get("off_msg") or "").startswith("The effects of blur wear off"))
sent.clear(); tick()
check(f"recasts after it wore off ({sent})", "blur" in sent)
st.buffs = [{"name": "Mageshield", "cast": "mshi", "enabled": True}]
for _ in range(2):
    s.bot.x.note_cast_buff("mshi")
    feed("You cast mageshield!", "The following people are in your travel party:")
check("never learns party output as a start message", not st.buffs[0].get("on_msg"))
st.buffs = []
# --- party heals
st.party_heal = True; st.party_heal_cmd = "mihe {name}"; st.party_heal_pct = 80
st.party_major_cmd = "mahe {name}"; st.party_major_pct = 50
st.party_area_cmd = "gheal"; st.party_area_count = 3; st.party_area_pct = 80
def par(rows):
    feed("[HP=600/MA=300]: par", "The following people are in your travel party:", *rows, "[HP=600/MA=300]:")
par(["  Tester Abil (Druid)  [M:100%] [H:100%] - Backrank",
     "  Miserable Par (Mage)  [M: 50%] [H: 45%]M - Frontrank",
     "  Revolution Abil (Priest) [M: 90%] [H: 75%]R - Backrank"])
sent.clear(); tick()
check("party major heal for 45%", "mahe Miserable" in sent)
par(["  Tester Abil (Druid)  [M:100%] [H:70%] - Backrank",
     "  Miserable Par (Mage)  [M: 50%] [H: 65%]M - Frontrank",
     "  Revolution Abil (Priest) [M: 90%] [H: 75%]R - Backrank"])
s.state.hp = 420
st.heal_pct = 50
sent.clear(); tick()
check("area heal when 3 below 80%", "gheal" in sent)
s.state.hp = 600; st.party_heal = False
# --- party bless
st.party_blesses = [{"cast": "prot", "secs": 0, "enabled": True}, {"cast": "bles {name}", "secs": 60, "enabled": True}]
sent.clear(); tick(4)
check("party blesses cast (group + each member)", "prot" in sent and "bles Miserable" in sent and "bles Revolution" in sent)
sent.clear(); tick(3)
check("not again until their time", not any(c.startswith(("prot", "bles")) for c in sent))
st.party_blesses = []
# --- PvP spells: mist every 25 rounds, slep every round, then melee
st.pvp_spells = [{"cast": "mist", "rounds": 25}, {"cast": "slep", "rounds": 0}]
feed("[HP=600/MA=300]:Town Gates", "Also here: Bob.", "Obvious exits: north, south")
s.bot.x.start_pvp("Bob")
seq = []
for _ in range(4):
    sent.clear(); s.bot._cool = {"par": time.time(), "par_solo": time.time()}; s.bot.tick(); seq += sent
check(f"PvP order mist, slep, slep, slep (got {seq})", seq[:4] == ["mist Bob", "slep Bob", "slep Bob", "slep Bob"])
s.bot.x.stop_pvp()
# --- path builder logic (routes through MME, saves as MegaMUD path)
w = s.world
pts = [(1, 1), (1, 16), (1, 224)]
route = []
for a, b in zip(pts + [pts[0]], (pts + [pts[0]])[1:]):
    route += w.route(a, b)
mp = path_from_route(w, pts[0], route, name="Built loop")
check(f"built loop: {len(mp.steps)} steps, is loop", mp.is_loop and len(mp.steps) == len(route) and mp.steps[0].room == (1, 1))
print("ALL PASS" if ok else "SOME FAILED")
