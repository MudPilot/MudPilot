"""Bless wear-off / start messages: a hit that 'vanishes' isn't a wear-off; another bless's start line isn't ours."""
import os, sys, time
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config, spells
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
spells.spell_duration = lambda sp, lvl: 60
s.bot.spell_for_cast = lambda key: object()
x = s.bot.x
st.buffs = [{"name": "blur", "cast": "blur", "enabled": True}]
s.bot._buff_cast["blur"] = time.time() - 50
x.note_line("A fire elemental appears and scorches large nightshade for 300 damage, then vanishes!")
check("a fire elemental hit isn't learned as blur wearing off", not st.buffs[0].get("off_msg"))
x.note_line("You are no longer blurred.")
check("a real wear-off line is still learned", st.buffs[0].get("off_msg") == "You are no longer blurred.")
# a wear-off line that names a bless goes to that bless only (0.8.69 live: mshi learned "The mana flux dissipates")
st.buffs = [{"name": "mshi", "cast": "mshi"}, {"name": "Mana flux", "cast": "flux", "off_msg": ""}]
s.bot._buff_cast["mshi"] = time.time() - 50
x.note_line("The mana flux dissipates rapidly.")
check("flux's wear-off isn't pinned on mshi", not st.buffs[0].get("off_msg"))
check("…it goes to Mana flux", st.buffs[1].get("off_msg") == "The mana flux dissipates rapidly.")
# another bless's known wear-off line isn't learned again for this one (0.8.70 live: mshi got armr's)
st.buffs = [{"name": "mshi", "cast": "mshi"},
            {"name": "armr", "cast": "armr", "off_msg": "The effects of magic armour wear off!"}]
s.bot._buff_cast["mshi"] = time.time() - 50
x.note_line("The effects of magic armour wear off!")
check("armr's wear-off isn't learned for mshi", not st.buffs[0].get("off_msg"))
# the spell's own name counts too (MME records use "Name")
s.bot.spell_for_cast = lambda key: {"Name": "Magic Armour"} if key == "armr" else {"Name": "Mageshield"}
st.buffs = [{"name": "mshi", "cast": "mshi"}, {"name": "armr", "cast": "armr"}]
x.note_line("The effects of magic armour wear off!")
check("a line naming the spell goes to that bless", st.buffs[1].get("off_msg") and not st.buffs[0].get("off_msg"))
s.bot.spell_for_cast = lambda key: object()
# start message: blur's line right after a flux cast isn't flux's
st.buffs = [{"name": "blur", "cast": "blur", "on_msg": "You are blurred!"}, {"name": "Mana flux", "cast": "flux"}]
for _ in range(2):
    x._last_cast_buff = ("flux", time.time(), True)
    x.note_line("You are blurred!")
check("another bless's start line isn't learned for flux", not st.buffs[1].get("on_msg"))
print("ALL PASS" if ok else "SOME FAILED"); sys.exit(0 if ok else 1)
