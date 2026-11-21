"""Bless lengths learned from 'st' (Paradigm: 'You feel protected! (216s)') per level, and used for the recast;
'st' is read after casting a bless and every few minutes."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"
s = Session(st)
class T:
    connected = True
    events = __import__("queue").Queue()
    def send_line(self, x): pass
    def close(self): self.connected = False
s.telnet = T()
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
b = s.bot
st.char_level = 47
st.bless_margin_secs = 15
mshi = {"name": "mshi", "cast": "mshi", "on_msg": "You feel protected!"}
blur = {"name": "blur", "cast": "blur", "on_msg": "You are blurred!"}
st.buffs = [mshi, blur]
ST = ["Name: Miserable Revolution             Lives/CP:      8/0",
      "Willpower: 60     Charm:   60          MagicRes:       82",
      "You are in a dream state! (25893s)", "You are blurred! (27s)", "You feel protected! (216s)"]
b._buff_cast["mshi"] = time.time() - 4                 # just cast: st shows (nearly) its full length
b._buff_cast["blur"] = time.time() - 300               # cast long ago: its 27s left is no length to learn
for l in ST:
    b.note_line(l)
check("mshi's real length learned at this level", b.learned_duration(mshi) in (219, 220, 221))
check("blur's length isn't guessed from an old cast", b.learned_duration(blur) is None)
need, why = b.buff_status(mshi)
check("mshi recast lined up with st: ~200s away", not need and why.startswith("recast in") and
      190 <= int(why.split()[2].rstrip("s")) <= 205)
st.char_level = 48
check("level up: relearned, not reused", b.learned_duration(mshi) is None)
st.char_level = 47
b._st_read = time.time() - 10
b._buff_cast["blur"] = time.time() - 3
check("st read a few seconds after a cast", b._st_due(st.buffs))
b._cool.pop("st_timers", None)
b._buff_cast["blur"] = b._buff_cast["mshi"] = b._st_read - 30
check("…not again until 3 minutes later", not b._st_due(st.buffs))
b._st_read = time.time() - 200
check("…then again", b._st_due(st.buffs))
# stock MajorMUD: 'st' shows no time-left lines → after two such readings, stop asking
STOCK = ["Name: Miserable Revolution             Lives/CP:      8/0",
         "Willpower: 60     Charm:   60          MagicRes:       82"]
for _ in range(2):
    b._buff_cast["blur"] = time.time() - 10
    for l in STOCK:
        b.note_line(l)
    b._st_read -= 5
b._st_judge()
b._buff_cast["blur"] = time.time() - 3
check("a board whose st shows no timers: no more st reads", not b._st_due(st.buffs))
b._st_read = time.time()
b.note_line("You are blurred! (27s)")
b._st_read -= 200
b._cool.pop("st_timers", None)
check("…but timers showing up again turns it back on", b._st_due(st.buffs))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
