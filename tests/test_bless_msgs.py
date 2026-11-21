"""Dan, 2026-10-28: a bless that drops should be known from its end message. Learned guesses were wrong —
mageshield's 'end' was "The effects of the poison wear off!", blur's was mageshield's "shimmers and fades". Each
bless now takes its start/end lines from the Messages file (MegaMUD's, bundled), by its spell name first (two spells
start "You feel protected"), and a guess never takes another spell's line."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from mudpilot import config
from mudpilot.session import Session
here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
st = config.Settings(); st.save = lambda: None; st.my_name = "Miserable"; st.char_level = 47
st.buffs = [
    {"cast": "mshi", "name": "mageshield", "on_msg": "You feel protected!", "off_msg": "The effects of the poison wear off!",
     "off_msg_learned": True},
    {"cast": "blur", "on_msg": "You are blurred!", "off_msg": "Your mageshield shimmers and fades.", "off_msg_learned": True},
    {"cast": "chao", "on_msg": "You are surrounded by a chaos shield!"},
    {"cast": "armr", "on_msg": "You feel armoured!", "off_msg": "My own line", "off_msg_learned": False},
]
s = Session(st, world_path=os.path.join(here, "mudpilot", "bundled", "Paradigm.db")); s._no_log_file = True
ok = True
def check(n, c):
    global ok; ok &= bool(c); print(("PASS " if c else "FAIL ") + n)
x = s.bot.x
x.fix_bless_messages()
off = {b["cast"]: b.get("off_msg") for b in st.buffs}
check(f"mageshield: its own end line ({off['mshi']})", off["mshi"] == "Your mageshield shimmers and fades")
check(f"blur: its own ({off['blur']})", off["blur"] == "The effects of blur wear off")
check(f"chaos shield: learned from the file ({off['chao']})", off["chao"] == "The chaos shield fizzles out")
check("a line you typed yourself is kept", off["armr"] == "My own line")
x._learn_off("The effects of the poison wear off!")
check("poison ending doesn't get filed under a bless", all(b.get("off_msg") != "The effects of the poison wear off!" for b in st.buffs))
print("ALL PASS" if ok else "SOME FAILED")
sys.exit(0 if ok else 1)
